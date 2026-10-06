# Change: remove-static-token

## Why

静态 `MCP_AUTH_TOKEN` 在 project.md 中即标注为「临时方案，将被 OAuth 取代」。截至 2026-10-06，移除条件已成熟：

1. **连接器已切 OAuth**：企业连接器 `enterprise_ruixin_test_demo` 已配通（2026-10-06 WorkBuddy 实测，`odoo_ping` connected，17 工具可用），云端同时段日志全部为 `oauth verify ... allow`。
2. **静态 token 零使用**：云端 7 天 journal 审计 `static allow=0` / `oauth allow=75` / `deny=7`，无任何合法静态流量。
3. **攻击面**：静态 token 以明文长期存于云端主 unit 文件（`/etc/systemd/system/odoo-mcp.service`），是永久有效的共享凭据；与 OAuth 短期令牌并存只增泄露面，且 both 模式下静态比对短路优先于 OAuth 校验。

## What Changes

1. 移除 `static` / `both` 模式：删除 `_StaticTokenMiddleware`、`_StaticTokenMatcher` 及 `OAuthBearerMiddleware` 的静态比对短路；`MCP_AUTH_TOKEN` 环境变量废止。
2. `MCP_AUTH_MODE` 收窄：仅接受 `oauth`（缺省 `oauth`）；`static`/`both`/其他值启动时抛 ValueError（fail-fast，暴露残留配置而非静默忽略）。
3. spec 同步补登两项已上线未入档的能力（随本 change 一并归档）：RFC 7662 introspection 校验路径；RFC 9728 资源元数据端点 + 401 挑战头 + 豁免路径（代码见 commit ba7668da7fa）。
4. 云端执行：主 unit 删除 `MCP_AUTH_TOKEN` 行、override.conf 改 `MCP_AUTH_MODE=oauth`，daemon-reload + restart，按验证矩阵实测（含 WorkBuddy 连接器回归）。

## What NOT Changes（明确排除）

- 不动 introspection/userinfo 双协议、正负缓存、降级（503）策略、日志脱敏；
- 不动豁免路径与 well-known 输出内容；不动 IdP（odoomcp.duckdns.org）与 Caddy；
- 不动 stdio 传输（本机 stdio 无鉴权，行为不变）与工具层。

## Impact

- **代码**：`src/odoo_mcp_server/auth.py`（删静态路径，约 70 行）；`server.py` 装配调用不变。
- **配置**：`MCP_AUTH_TOKEN` 废止；`MCP_AUTH_MODE` 语义收窄；README 与 `.env.example` 同步。
- **规格**：`openspec/specs/mcp-auth/spec.md`（MODIFIED 模式开关/OAuth 校验/降级/已知限制，ADDED introspection + 发现端点）。
- **行为变更（破坏性）**：静态 token 请求由放行变为 401；无合法使用方（7 天审计为 0），如有个副本机/脚本仍用静态 token 需改领 OAuth token。
- **回滚**：云端 tar 快照（沿用 add-oauth-mcp-auth 5.1 机制，已演练验证）+ `git revert`；回滚即恢复 both。
