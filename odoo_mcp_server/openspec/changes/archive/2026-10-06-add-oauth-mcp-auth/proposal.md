# Change: add-oauth-mcp-auth

## Why

当前 HTTP 传输仅有静态 `MCP_AUTH_TOKEN` 一种鉴权（`_BearerAuthMiddleware`），无法支撑"用户经 CodeBuddy 账号 OAuth 登录后访问连接器"的目标形态。企业连接器（oauth2_code）会以 `Authorization: Bearer <access_token>` 注入用户令牌，MCP Server 必须能校验该令牌真伪。

已验证事实（change `fix-oauth-endpoints` 归档结论）：CodeBuddy 开放平台（`copilot.tencent.com/oauth2`，Keycloak）授权码流程可用，token 为 RS256 JWT，`GET /oauth2/userinfo` 携带用户令牌返回 200 + 用户信息、返回 401 表示无效。

## What Changes

1. 新增 OAuth Bearer 校验中间件：取请求 Bearer token → 调 `OAUTH_USERINFO_ENDPOINT` 验证 → 200 放行 / 401 拒绝；带 TTL 缓存与负缓存；userinfo 不可达时按降级策略处理（缓存命中放行，否则 503）。
2. 新增 `MCP_AUTH_MODE=static|oauth|both` 三态开关（默认 `both`，过渡期新旧并存——**这是秒级回滚的核心**）；`static` 行为与现状完全一致。
3. 保留静态 token 中间件不删；静态比较改用 `hmac.compare_digest`（顺手加固）。
4. 日志脱敏：只记录 token 的 SHA-256 前 8 位，绝不记录原文。
5. 落地 `specs/mcp-auth` 基线规格（specs/ 当前为空，以 ADDED 形成基线）。

## What NOT Changes（明确排除）

- 不动 `client.py`、不动 Odoo 服务账号模式、不动 stdio/sse 传输、不动工具实现；
- 不做用户→Odoo 身份透传（方案 B，另行提案）；
- 不做 refresh_token；token 过期由连接器/用户重新登录解决。

## Impact

- **代码**：新增 `src/odoo_mcp_server/auth.py`；`server.py` 的 `_run_http` 按 `MCP_AUTH_MODE` 装配中间件（`_BearerAuthMiddleware` 保留）。
- **配置**：新增 `MCP_AUTH_MODE`、`OAUTH_USERINFO_ENDPOINT`（默认 `https://copilot.tencent.com/oauth2/userinfo`）、`OAUTH_TOKEN_CACHE_TTL`（默认 300s）；README 与 `.env.example` 同步。
- **对侧提案**：`codebuddyOauth/openspec/changes/add-oauth-mcp-auth/`（token 领取页，供演示取 token 配入 MCP 客户端）。
- **规格**：新增 `openspec/specs/mcp-auth/spec.md`（归档时合并）。
- **回滚**：云端 `systemctl edit odoo-mcp` 设 `MCP_AUTH_MODE=static` + restart，<1 分钟恢复现状；代码层 `git revert`；部署层阶段 3 有 tar 快照。
