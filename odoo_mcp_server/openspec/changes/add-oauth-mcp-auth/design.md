# Design: OAuth Bearer 校验中间件

## Context

- 现状：`_BearerAuthMiddleware`（server.py:246）做静态 token 比对；云端 systemd 以 `MCP_AUTH_TOKEN` 运行。
- 目标形态：企业连接器（oauth2_code）注入用户 OAuth token；演示过渡期静态 token 仍需可用（既有 MCP 客户端配置不动）。
- 约束：`mcp>=1.8.0,<2.0`；纯 ASGI 中间件栈（uvicorn 承载）；云端新加坡节点出网可达 `copilot.tencent.com`；公司办公网代理会拦该域名（本机开发需注意）。

## Goals & Non-Goals

- Goals：`MCP_AUTH_MODE` 三态切换；OAuth 校验有缓存、有降级、可观测（脱敏日志）；静态路径行为与现状零差异。
- Non-Goals：JWT 本地验签（需维护 JWKS 拉取/轮换，演示期 userinfo 在线校验足够，spec 留扩展位）；多 IdP 自动发现；rate limiting。

## Decisions

### D1：校验协议 = userinfo 在线校验（默认），introspection 可选
- `GET OAUTH_USERINFO_ENDPOINT`，`Authorization: Bearer <token>`；200→有效（缓存 userinfo），401→无效；其他 4xx（实测 403=token 缺 `openid` scope）同按无效处理并负缓存。
- 选 userinfo 而非 introspection：copilot.tencent.com 对 client_credentials token 的 userinfo 返回空但 200（已实测），行为一致可用；introspection 端点 Keycloak 通常要求 resource-server 专用凭据，演示期不引入额外凭据管理。
- oauthDemo 兜底 IdP 用 `/me`（userinfo 等价物），同一协议可覆盖，只需改 `OAUTH_USERINFO_ENDPOINT` 指向。

### D2：缓存策略
- 正缓存：校验通过 → 缓存 `(fetched_at, userinfo)`，TTL=`OAUTH_TOKEN_CACHE_TTL`（默认 300s）。
- 负缓存：401 → 缓存无效标记，TTL=60s（避免对同一坏 token 反复出网）。
- key = token 的 SHA-256；容量上限 1024，超出按 FIFO 淘汰；进程内存态，重启即清（可接受）。

### D3：降级（userinfo 不可达 = 网络错误/5xx/超时>5s）
- 该 token 有未过期正缓存 → 放行（最后一次已知状态为有效）。
- 否则 → **503**（`{"error":"auth_unavailable"}`），与 401 区分，便于客户端/运维识别是 IdP 故障而非凭证问题。

### D4：`MCP_AUTH_MODE` 装配（`_run_http`）
- `static`：仅静态中间件（现状，默认回滚位）。
- `oauth`：仅 OAuth 中间件。
- `both`（默认）：先静态比对（`hmac.compare_digest`，常数时间），不匹配再走 OAuth 校验；一次请求只走一条路径。
- `MCP_AUTH_TOKEN` 未设置且 mode 含 static → static 路径视为不匹配（不报错，交由 oauth/401）。

### D5：日志与安全
- 日志仅记录 `sha256(token)[:8]`、校验结果、缓存命中与否、userinfo 时延；MUST NOT 记录 token 原文与 Authorization 头。
- 非 HTTP scope（lifespan 等）直接透传（沿用现状约定）。

## Risks

| 风险 | 缓解 |
| --- | --- |
| userinfo 被刷（恶意随机 token 打爆出网） | 负缓存 60s + 5s 超时；演示环境风险可接受 |
| Keycloak 撤销 token 但缓存仍放行 | TTL 300s 上限；演示可接受，spec 注明 |
| 云端→copilot.tencent.com 网络抖动 | D3 降级 + 503 可观测 |
| 模式开关拼写错误 | 非法值启动即 `ValueError`（fail-fast，不静默降级为无鉴权） |
