"""HTTP 传输鉴权中间件（change: add-oauth-mcp-auth）。

三种模式（环境变量 MCP_AUTH_MODE，默认 both）：
- static：仅静态 Bearer Token 校验（hmac.compare_digest 常数时间比较），行为与改造前一致；
- oauth：仅 OAuth Bearer 校验（调 OAUTH_USERINFO_ENDPOINT 在线验证，带正负缓存与降级）；
- both：先静态比对，不匹配再走 OAuth 校验；一次请求只走一条路径。

安全约定（design D5）：日志只记录 sha256(token) 前 8 位，绝不记录 token 原文与
Authorization 头；非 HTTP scope（lifespan 等）直接透传。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from collections import OrderedDict
from typing import Any

import httpx

logger = logging.getLogger("odoo_mcp.auth")

DEFAULT_USERINFO_ENDPOINT = "https://copilot.tencent.com/oauth2/userinfo"
DEFAULT_CACHE_TTL = 300.0  # 正缓存 TTL（秒）
NEG_CACHE_TTL = 60.0  # 负缓存 TTL（秒）
CACHE_CAPACITY = 1024
USERINFO_TIMEOUT = 5.0


def _token_fp(token: str) -> str:
    """token 指纹：sha256 前 8 位（日志脱敏用）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def _extract_bearer(scope: Any) -> str | None:
    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization", b"").decode("latin-1")
    if not auth.startswith("Bearer "):
        return None
    token = auth[len("Bearer "):].strip()
    return token or None


async def _send_json(send: Any, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


class _TokenCache:
    """进程内 FIFO 缓存：key=sha256(token)，value={"kind": "pos"|"neg", "at": monotonic, "userinfo": ...}。

    正缓存 TTL=OAUTH_TOKEN_CACHE_TTL（默认 300s），负缓存 TTL=60s；
    容量上限 1024，超出按 FIFO 淘汰；进程重启即清。
    """

    def __init__(self, capacity: int = CACHE_CAPACITY) -> None:
        self._entries: OrderedDict[str, dict] = OrderedDict()
        self._capacity = capacity

    def get(self, key: str) -> dict | None:
        return self._entries.get(key)

    def put(self, key: str, entry: dict) -> None:
        self._entries[key] = entry
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)


class _StaticTokenMatcher:
    """静态 token 比对（常数时间）。token 未配置时视为永不匹配（fail-closed，design D4）。"""

    def __init__(self, token: str | None) -> None:
        self._token = token.encode("utf-8") if token else None

    @property
    def configured(self) -> bool:
        return self._token is not None

    def matches(self, token: str | None) -> bool:
        if self._token is None or token is None:
            return False
        return hmac.compare_digest(token.encode("utf-8"), self._token)


class _StaticTokenMiddleware:
    """纯 ASGI 中间件：所有 HTTP 请求必须带正确的静态
    `Authorization: Bearer <token>`，否则 401。非 HTTP scope 直接透传。"""

    def __init__(self, app: Any, token: str | None) -> None:
        self.app = app
        self._matcher = _StaticTokenMatcher(token)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if not self._matcher.matches(_extract_bearer(scope)):
            await _send_json(send, 401, b'{"error": "unauthorized"}')
            return
        await self.app(scope, receive, send)


class OAuthBearerMiddleware:
    """OAuth Bearer 校验中间件（纯 ASGI）。

    校验协议（design D1）：GET userinfo 端点，Authorization: Bearer <token>；
    200→有效（正缓存），401→无效（负缓存 60s）。
    降级（design D3）：userinfo 不可达（网络错误/超时/非 200/401）时，
    该 token 有未过期正缓存则放行，否则 503 {"error":"auth_unavailable"}。
    static_token 非空时（both 模式）先做静态比对，命中直接放行。
    """

    def __init__(
        self,
        app: Any,
        userinfo_endpoint: str,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        static_token: str | None = None,
    ) -> None:
        self.app = app
        self._endpoint = userinfo_endpoint
        self._ttl = cache_ttl
        self._cache = _TokenCache()
        self._static = _StaticTokenMatcher(static_token)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=USERINFO_TIMEOUT)
        return self._client

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        token = _extract_bearer(scope)

        # both 模式：先静态比对（常数时间），命中直接放行
        if self._static.matches(token):
            await self.app(scope, receive, send)
            return

        if token is None:
            await _send_json(send, 401, b'{"error": "unauthorized"}')
            return

        ok, status = await self._verify(token)
        if ok:
            await self.app(scope, receive, send)
        elif status == 503:
            await _send_json(send, 503, b'{"error": "auth_unavailable"}')
        else:
            await _send_json(send, 401, b'{"error": "unauthorized"}')

    async def _verify(self, token: str) -> tuple[bool, int]:
        key = hashlib.sha256(token.encode("utf-8")).hexdigest()
        fp = key[:8]
        now = time.monotonic()

        entry = self._cache.get(key)
        if entry is not None:
            if entry["kind"] == "pos" and now - entry["at"] < self._ttl:
                logger.info("oauth verify token=%s result=allow cache=pos-hit", fp)
                return True, 200
            if entry["kind"] == "neg" and now - entry["at"] < NEG_CACHE_TTL:
                logger.info("oauth verify token=%s result=deny cache=neg-hit", fp)
                return False, 401

        start = time.monotonic()
        try:
            client = await self._get_client()
            resp = await client.get(
                self._endpoint, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "oauth verify token=%s userinfo unreachable error=%s latency_ms=%d -> 503",
                fp,
                type(exc).__name__,
                latency_ms,
            )
            return False, 503

        latency_ms = int((time.monotonic() - start) * 1000)
        if resp.status_code == 200:
            try:
                userinfo = resp.json()
            except ValueError:
                userinfo = None
            self._cache.put(key, {"kind": "pos", "at": now, "userinfo": userinfo})
            logger.info(
                "oauth verify token=%s result=allow cache=miss latency_ms=%d",
                fp,
                latency_ms,
            )
            return True, 200
        if resp.status_code >= 500:
            logger.warning(
                "oauth verify token=%s userinfo unexpected status=%d latency_ms=%d -> 503",
                fp,
                resp.status_code,
                latency_ms,
            )
            return False, 503

        # 401 及其他 4xx（如 403：token 缺 openid scope）→ 无效，负缓存 60s
        self._cache.put(key, {"kind": "neg", "at": now})
        logger.info(
            "oauth verify token=%s result=deny status=%d cache=miss latency_ms=%d",
            fp,
            resp.status_code,
            latency_ms,
        )
        return False, 401


def _env_userinfo_endpoint() -> str:
    return (
        os.environ.get("OAUTH_USERINFO_ENDPOINT", DEFAULT_USERINFO_ENDPOINT).strip()
        or DEFAULT_USERINFO_ENDPOINT
    )


def _env_cache_ttl() -> float:
    raw = os.environ.get("OAUTH_TOKEN_CACHE_TTL", "").strip()
    try:
        return float(raw) if raw else DEFAULT_CACHE_TTL
    except ValueError:
        logger.warning("OAUTH_TOKEN_CACHE_TTL=%r 非法，回退默认 %ss", raw, DEFAULT_CACHE_TTL)
        return DEFAULT_CACHE_TTL


def build_auth_middleware(app: Any, mode: str) -> Any:
    """按 MCP_AUTH_MODE 装配鉴权中间件。非法 mode 抛 ValueError（fail-fast）。"""
    normalized = (mode or "").strip().lower()
    static_token = os.environ.get("MCP_AUTH_TOKEN", "").strip() or None

    if normalized == "static":
        logger.info(
            "auth mode=static (static_token=%s)",
            "configured" if static_token else "missing(fail-closed)",
        )
        return _StaticTokenMiddleware(app, static_token)
    if normalized == "oauth":
        logger.info("auth mode=oauth userinfo=%s", _env_userinfo_endpoint())
        return OAuthBearerMiddleware(app, _env_userinfo_endpoint(), _env_cache_ttl())
    if normalized == "both":
        logger.info(
            "auth mode=both userinfo=%s static_token=%s",
            _env_userinfo_endpoint(),
            "configured" if static_token else "missing",
        )
        return OAuthBearerMiddleware(
            app, _env_userinfo_endpoint(), _env_cache_ttl(), static_token=static_token
        )
    raise ValueError(
        f"非法 MCP_AUTH_MODE: {mode!r}（可选值: static | oauth | both）"
    )
