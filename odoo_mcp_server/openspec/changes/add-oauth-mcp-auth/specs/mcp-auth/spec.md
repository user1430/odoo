# Delta: mcp-auth（基线新增）

## ADDED Requirements

#### Requirement: 鉴权模式开关

MCP Server 的 HTTP 传输 SHALL 支持 `MCP_AUTH_MODE` 环境变量，取值 `static` / `oauth` / `both`（缺省 `both`）；非法取值 MUST 在启动时以 `ValueError` 失败，不得静默放行。`static` 模式行为 MUST 与改造前完全一致（`MCP_AUTH_TOKEN` 未设置时视为不匹配）。

##### Scenario: 非法模式值

- **WHEN** `MCP_AUTH_MODE=xyz` 启动 HTTP 传输
- **THEN** 进程以 ValueError 退出，不监听端口

##### Scenario: both 模式双通道

- **WHEN** `MCP_AUTH_MODE=both` 且设置了 `MCP_AUTH_TOKEN`
- **THEN** 携带正确静态 token 的请求被放行，携带有效 OAuth token 的请求亦被放行
- **AND** 同一请求只经一条校验路径（静态优先）

#### Requirement: OAuth Bearer 令牌校验

`oauth` 路径 SHALL 以请求 `Authorization: Bearer <token>` 调用 `OAUTH_USERINFO_ENDPOINT`（默认 `https://copilot.tencent.com/oauth2/userinfo`）在线校验：HTTP 200 视为有效并缓存（TTL=`OAUTH_TOKEN_CACHE_TTL`，默认 300s）；HTTP 401 及其他 4xx（如 403=token 缺 `openid` scope）视为无效并负缓存（TTL 60s）；校验通过 SHALL 放行请求，无效 SHALL 返回 401 `{"error":"unauthorized"}`。

##### Scenario: 有效令牌放行

- **WHEN** 请求携带 IdP 签发的未过期 access_token
- **THEN** 中间件放行，MCP 方法正常执行
- **AND** TTL 内相同 token 的后续请求命中正缓存，不再出网

##### Scenario: 无效令牌拒绝

- **WHEN** 请求携带伪造/过期 token
- **THEN** 返回 401，60s 内重复请求命中负缓存

#### Requirement: 校验服务降级

当 userinfo 端点不可达（网络错误、5xx、超时 >5s）：若该 token 存在未过期正缓存 SHALL 放行；否则 SHALL 返回 503 `{"error":"auth_unavailable"}`（与 401 区分，标识 IdP 故障而非凭证无效）。

##### Scenario: IdP 故障无缓存

- **WHEN** userinfo 不可达且请求 token 无正缓存
- **THEN** 返回 503 auth_unavailable

##### Scenario: IdP 故障有缓存

- **WHEN** userinfo 不可达但该 token 正缓存未过期
- **THEN** 请求放行

#### Requirement: 日志脱敏

鉴权日志 MUST NOT 记录 token 原文或完整 Authorization 头；SHALL 以 `sha256(token)[:8]` 作为标识，记录校验结果、缓存命中与 userinfo 时延。非 HTTP scope（lifespan 等）MUST 直接透传不鉴权。

##### Scenario: 日志不含原文

- **WHEN** 任意鉴权事件发生后检查 stderr 日志
- **THEN** 不存在 token 原文，仅存在其 sha256 前 8 位

#### Requirement: 已知限制（演示期接受）

实测（2026-10-06）：copilot realm 的 userinfo 仅校验签名与有效期，**不检查 SSO 会话与吊销状态**——IdP 登出、POST /oauth2/revoke（302 非标准端点）均不能使未过期 token 失效；本中间件以 userinfo 为准，故此类 token 在到期前始终放行。缓存放行另叠加最长 300s 的撤销感知延迟。后续如需更强一致性 SHALL 可替换为 JWT 本地验签（JWKS）或 introspection 端点，本规格不阻塞该演进。
