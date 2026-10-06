"""HTTP 传输 OAuth 鉴权中间件。

在线校验 Bearer token：introspection（RFC 7662，配置后优先）或 userinfo，
带正负缓存与降级。MCP_AUTH_MODE 仅接受 oauth（缺省即 oauth）；静态 token
通道已随 change remove-static-token 移除（static/both 启动即 ValueError）。

安全约定：日志只记录 sha256(token) 前 8 位，绝不记录 token 原文与
Authorization 头；非 HTTP scope（lifespan 等）直接透传。
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from collections import OrderedDict
from typing import Any

import httpx

logger = logging.getLogger("odoo_mcp.auth")

DEFAULT_USERINFO_ENDPOINT = "https://odoomcp.duckdns.org/me"
DEFAULT_CACHE_TTL = 300.0  # 正缓存 TTL（秒）
NEG_CACHE_TTL = 60.0  # 负缓存 TTL（秒）
CACHE_CAPACITY = 1024
USERINFO_TIMEOUT = 5.0

# OAuth 基础设施端点豁免鉴权（RFC 9728/8414/7591 发现流程必须匿名可访问）：
# /.well-known/* 前缀 + AS 侧端点（本机未实现时匿名 404，而非 401）。
EXEMPT_PATH_PREFIXES = ("/.well-known/",)
EXEMPT_PATHS = frozenset({"/", "/health", "/register", "/authorize", "/token"})


def _is_exempt(scope: Any) -> bool:
    """OAuth 发现/注册等基础设施端点豁免 Bearer 校验。"""
    path = scope.get("path", "")
    return path in EXEMPT_PATHS or path.startswith(EXEMPT_PATH_PREFIXES)


def _resource_metadata_url() -> str:
    raw = os.environ.get("OAUTH_RESOURCE_METADATA_URL", "").strip()
    if raw:
        return raw
    base = os.environ.get("MCP_PUBLIC_URL", "https://odoomcpdemo.duckdns.org")
    return base.strip().rstrip("/") + "/.well-known/oauth-protected-resource/mcp"


def _bearer_challenge_header() -> tuple[bytes, bytes]:
    """RFC 9728 §5.1：401 必须携带 WWW-Authenticate 指向资源元数据。"""
    value = f'Bearer resource_metadata="{_resource_metadata_url()}"'
    return (b"www-authenticate", value.encode("latin-1"))


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


async def _send_json(
    send: Any,
    status: int,
    body: bytes,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    headers = [(b"content-type", b"application/json")]
    if extra_headers:
        headers.extend(extra_headers)
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers,
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


class OAuthBearerMiddleware:
    """OAuth Bearer 校验中间件（纯 ASGI）。

    校验协议（二选一，introspection 优先）：
    - introspection（RFC 7662）：POST 端点，client_secret_post 认证，active=true 放行。
      适用于 token 带 audience（RFC 8707）的 IdP——userinfo 会拒绝此类 token。
    - userinfo：GET 端点，Authorization: Bearer <token>；200→有效。
    均带正负缓存；降级：校验端点不可达时，该 token 有未过期
    正缓存则放行，否则 503 {"error":"auth_unavailable"}。
    """

    def __init__(
        self,
        app: Any,
        userinfo_endpoint: str,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        introspection: dict | None = None,
    ) -> None:
        self.app = app
        self._endpoint = userinfo_endpoint
        self._introspection = introspection  # {"endpoint","client_id","client_secret"} 或 None
        self._ttl = cache_ttl
        self._cache = _TokenCache()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=USERINFO_TIMEOUT)
        return self._client

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if _is_exempt(scope):
            await self.app(scope, receive, send)
            return

        token = _extract_bearer(scope)
        if token is None:
            await _send_json(
                send, 401, b'{"error": "unauthorized"}', [_bearer_challenge_header()]
            )
            return

        ok, status = await self._verify(token)
        if ok:
            await self.app(scope, receive, send)
        elif status == 503:
            await _send_json(send, 503, b'{"error": "auth_unavailable"}')
        else:
            await _send_json(
                send, 401, b'{"error": "unauthorized"}', [_bearer_challenge_header()]
            )

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
            if self._introspection is not None:
                resp = await client.post(
                    self._introspection["endpoint"],
                    data={
                        "token": token,
                        "client_id": self._introspection["client_id"],
                        "client_secret": self._introspection["client_secret"],
                    },
                )
            else:
                resp = await client.get(
                    self._endpoint, headers={"Authorization": f"Bearer {token}"}
                )
        except httpx.HTTPError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "oauth verify token=%s verify-endpoint unreachable error=%s latency_ms=%d -> 503",
                fp,
                type(exc).__name__,
                latency_ms,
            )
            return False, 503

        latency_ms = int((time.monotonic() - start) * 1000)
        if resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            # introspection：200 仅代表请求合法，需 active=true 才是有效 token
            if self._introspection is not None and not (
                isinstance(payload, dict) and payload.get("active") is True
            ):
                self._cache.put(key, {"kind": "neg", "at": now})
                logger.info(
                    "oauth verify token=%s result=deny introspection-inactive latency_ms=%d",
                    fp,
                    latency_ms,
                )
                return False, 401
            self._cache.put(key, {"kind": "pos", "at": now, "userinfo": payload})
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


def _env_introspection() -> dict | None:
    """introspection（RFC 7662）配置。端点未配置返回 None（走 userinfo）；
    配置了端点但缺 client 凭据则 fail-fast（避免静默降级为全部 401）。"""
    endpoint = os.environ.get("OAUTH_INTROSPECTION_ENDPOINT", "").strip()
    if not endpoint:
        return None
    client_id = os.environ.get("OAUTH_INTROSPECTION_CLIENT_ID", "").strip()
    client_secret = os.environ.get("OAUTH_INTROSPECTION_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError(
            "已配置 OAUTH_INTROSPECTION_ENDPOINT 但缺少 "
            "OAUTH_INTROSPECTION_CLIENT_ID / OAUTH_INTROSPECTION_CLIENT_SECRET"
        )
    return {"endpoint": endpoint, "client_id": client_id, "client_secret": client_secret}


def _verify_desc(introspection: dict | None) -> str:
    return (
        f"introspection={introspection['endpoint']}"
        if introspection
        else f"userinfo={_env_userinfo_endpoint()}"
    )


def build_auth_middleware(app: Any, mode: str) -> Any:
    """装配 OAuth 鉴权中间件。mode 仅接受 oauth（空值视同 oauth）；
    static/both 已随 remove-static-token 移除，传入即 ValueError（fail-fast，
    暴露残留配置而非静默忽略）。"""
    normalized = (mode or "").strip().lower() or "oauth"
    introspection = _env_introspection()

    if normalized == "oauth":
        logger.info("auth mode=oauth %s", _verify_desc(introspection))
        return OAuthBearerMiddleware(
            app, _env_userinfo_endpoint(), _env_cache_ttl(), introspection=introspection
        )
    raise ValueError(
        f"非法 MCP_AUTH_MODE: {mode!r}（静态 token 通道已移除，仅支持 oauth；"
        "请同步删除环境中的 MCP_AUTH_TOKEN）"
    )
