# Spec: mcp-auth

MCP Server HTTP 传输鉴权能力规格（基线，2026-10-06 随 change `remove-static-token` 归档更新：静态 token 通道移除，补登 introspection 与 OAuth 发现端点）。

## Requirements

#### Requirement: 鉴权模式开关

MCP Server 的 HTTP 传输 SHALL 支持 `MCP_AUTH_MODE` 环境变量，取值仅 `oauth`（缺省 `oauth`）；`static` / `both` / 其他取值 MUST 在启动时以 `ValueError` 失败（错误文案指明静态通道已移除），不得静默放行或静默忽略。静态 token 通道已随 change `remove-static-token` 移除：`MCP_AUTH_TOKEN` 不再有任何效果，携带旧静态 token 的请求一律按无效 OAuth token 处理（401）。

##### Scenario: 非法模式值（含 static/both）

- **WHEN** `MCP_AUTH_MODE=static`（或 `both`、`xyz`）启动 HTTP 传输
- **THEN** 进程以 ValueError 退出，不监听端口，错误文案提示静态通道已移除

##### Scenario: 缺省即 oauth

- **WHEN** 未设置 `MCP_AUTH_MODE` 启动 HTTP 传输
- **THEN** 以 oauth 模式装配，启动日志含 `auth mode=oauth` 与校验协议端点

#### Requirement: OAuth Bearer 令牌校验

`oauth` 路径 SHALL 校验请求 `Authorization: Bearer <token>`，校验协议二选一（**introspection 优先**）：

- **introspection（RFC 7662）**：配置 `OAUTH_INTROSPECTION_ENDPOINT` 时启用，POST 该端点（`client_secret_post` 认证，凭据为 `OAUTH_INTROSPECTION_CLIENT_ID` / `OAUTH_INTROSPECTION_CLIENT_SECRET`）；HTTP 200 且响应 `active` 为 `true` 视为有效。配置了端点但缺凭据 MUST 启动 fail-fast（ValueError），不得静默降级。
- **userinfo**：未配置 introspection 时使用，GET `OAUTH_USERINFO_ENDPOINT`（默认 `https://odoomcp.duckdns.org/me`），HTTP 200 视为有效。

两种协议均：有效则缓存（TTL=`OAUTH_TOKEN_CACHE_TTL`，默认 300s）并放行；HTTP 401 及其他 4xx（如 403=token 缺 `openid` scope）视为无效并负缓存（TTL 60s）；introspection 返回 200 但 `active!=true` 同样视为无效并负缓存。无效 SHALL 返回 401 `{"error":"unauthorized"}`（带挑战头，见「OAuth 发现端点与 401 挑战头」）。

##### Scenario: 有效令牌放行

- **WHEN** 请求携带 IdP 签发的未过期 access_token
- **THEN** 中间件放行，MCP 方法正常执行
- **AND** TTL 内相同 token 的后续请求命中正缓存，不再出网

##### Scenario: 无效令牌拒绝

- **WHEN** 请求携带伪造/过期 token，或 introspection 返回 `active=false`
- **THEN** 返回 401，60s 内重复请求命中负缓存

##### Scenario: 带 audience 的 token

- **WHEN** IdP 按 RFC 8707 签发带 audience 的 opaque token（userinfo 会拒绝此类 token）
- **THEN** introspection 路径校验 `active=true` 放行

#### Requirement: 校验服务降级

当校验端点（introspection 或 userinfo）不可达（网络错误、5xx、超时 >5s）：若该 token 存在未过期正缓存 SHALL 放行；否则 SHALL 返回 503 `{"error":"auth_unavailable"}`（与 401 区分，标识 IdP 故障而非凭证无效）。

##### Scenario: IdP 故障无缓存

- **WHEN** 校验端点不可达且请求 token 无正缓存
- **THEN** 返回 503 auth_unavailable

##### Scenario: IdP 故障有缓存

- **WHEN** 校验端点不可达但该 token 正缓存未过期
- **THEN** 请求放行

#### Requirement: OAuth 发现端点与 401 挑战头

MCP Server SHALL 匿名暴露 RFC 9728 资源元数据端点 `/.well-known/oauth-protected-resource` 与 `/.well-known/oauth-protected-resource/mcp`，输出 `resource`（默认 `https://odoomcpdemo.duckdns.org/mcp`，可由 `MCP_PUBLIC_URL` 调整）与 `authorization_servers`（`OAUTH_AUTHORIZATION_SERVER` 可调，默认 `https://odoomcp.duckdns.org`）。OAuth 基础设施路径 MUST 豁免 Bearer 校验：`/.well-known/` 前缀及 `/`、`/health`、`/register`、`/authorize`、`/token`（本机未实现的 AS 端点匿名 404，而非 401）。所有鉴权 401 响应 MUST 携带 `WWW-Authenticate: Bearer resource_metadata="<资源元数据 URL>"`（RFC 9728 §5.1，`OAUTH_RESOURCE_METADATA_URL` 可整体覆盖）。

##### Scenario: MCP 客户端发现流程

- **WHEN** 客户端无 token 请求 `/mcp`
- **THEN** 返回 401 且响应头含 `WWW-Authenticate: Bearer resource_metadata="https://<host>/.well-known/oauth-protected-resource/mcp"`

##### Scenario: 资源元数据匿名可访问

- **WHEN** 匿名 GET `/.well-known/oauth-protected-resource/mcp`
- **THEN** 返回 200，JSON 含 `resource` 与 `authorization_servers`

##### Scenario: 未实现的 AS 端点

- **WHEN** 匿名请求 `/authorize`、`/token` 等 AS 侧端点
- **THEN** 返回 404（豁免鉴权，而非 401）

#### Requirement: 日志脱敏

鉴权日志 MUST NOT 记录 token 原文或完整 Authorization 头；SHALL 以 `sha256(token)[:8]` 作为标识，记录校验结果、缓存命中与校验端点时延。非 HTTP scope（lifespan 等）MUST 直接透传不鉴权。

##### Scenario: 日志不含原文

- **WHEN** 任意鉴权事件发生后检查 stderr 日志
- **THEN** 不存在 token 原文，仅存在其 sha256 前 8 位

#### Requirement: 已知限制（演示期接受）

- userinfo 路径（copilot realm 实测 2026-10-06）仅校验签名与有效期，**不检查 SSO 会话与吊销状态**——IdP 登出、POST /oauth2/revoke（302 非标准端点）均不能使未过期 token 失效；以 userinfo 为准时此类 token 在到期前始终放行。
- **introspection 路径可感知吊销**（自建 IdP `odoomcp.duckdns.org` 以 `active` 实时应答），现网以此为准；缓存放行另叠加最长 300s 的撤销感知延迟。
- 后续如需更强一致性 SHALL 可替换为 JWT 本地验签（JWKS），本规格不阻塞该演进。

##### Scenario: 登出后未过期 token（userinfo 路径）

- **WHEN** 用户在 IdP 登出后继续使用未过期 token（且该校验走 userinfo）
- **THEN** 请求仍被放行，直至 token 过期（已知限制，演示期接受）
