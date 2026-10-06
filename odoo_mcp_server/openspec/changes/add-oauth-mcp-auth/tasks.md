# Tasks: add-oauth-mcp-auth（odoo_mcp_server 侧）

## 1. 实现

- [x] 1.1 新增 `src/odoo_mcp_server/auth.py`：`_StaticTokenMiddleware`（自 server.py 迁入并改 `hmac.compare_digest`）、`OAuthBearerMiddleware`（userinfo 校验 + 正负缓存 + 降级）、`build_auth_middleware(app, mode)` 装配函数（非法 mode 抛 ValueError）
- [x] 1.2 `server.py::_run_http` 改用 `build_auth_middleware`；删除原 `_BearerAuthMiddleware`（行为由 static 路径完整承接）
- [x] 1.3 环境变量：`MCP_AUTH_MODE`（默认 both）、`OAUTH_USERINFO_ENDPOINT`、`OAUTH_TOKEN_CACHE_TTL`；更新 README 与 `.env.example`

## 2. 本地验证矩阵（本机 HTTP 模式，`MCP_TRANSPORT=streamable-http MCP_PORT=8081`）

- [x] 2.1 无 Authorization 头 → 401
- [x] 2.2 正确静态 token → 放行（initialize 成功，odoo_ping 返回 Odoo 18.0）
- [x] 2.3 错误静态 token → 401
- [x] 2.4 有效 OAuth token → 放行并完成 `tools/call odoo_ping`（平台 SMS 故障期间用 `client_credentials`+`scope=openid` token 对真实 Keycloak 端点验证通过；浏览器用户 token 待 3.1 联调复验）
- [x] 2.5 伪造 OAuth token → 401（且 60s 内重复请求命中负缓存，日志可见 cache=neg-hit）
- [x] 2.6 断网模拟 userinfo 不可达（杀 mock IdP 进程，等价于指向 127.0.0.1:9）：无缓存 token → 503；有正缓存 token → 放行
- [x] 2.7 `MCP_AUTH_MODE=static` 下 OAuth token → 401；`=oauth` 下静态 token → 401
- [x] 2.8 日志检查：无 token 原文，仅 sha256 前 8 位

## 3. 联调（依赖对侧任务 2.1 完成）

- [ ] 3.1 从 `http://127.0.0.1:3001` 登录复制完整 token，配置 MCP 客户端（`Authorization: Bearer <token>`）调本机 8081 → 全工具可用
- [ ] 3.2 token 过期后（或手动失效）→ 401，重新登录取新 token 恢复

## 4. 提交与归档

- [ ] 4.1 小步提交：实现 / 文档 / openspec 分开 commit
- [ ] 4.2 合并 spec 增量至 `openspec/specs/mcp-auth/spec.md`，change 移入 archive

## 5. 阶段 3：云端灰度（另起终端窗口执行，每步留快照）

- [ ] 5.1 云端快照：`tar czf /root/odoo-mcp-backup-$(date +%F).tgz /opt/odoo-mcp-server` + `systemctl cat odoo-mcp > ~/odoo-mcp.unit.bak`
- [ ] 5.2 部署新版 + `MCP_AUTH_MODE=both`，重启；静态 token 链路回归（既有客户端不受影响）
- [ ] 5.3 OAuth token 链路实测（经 `-L` 转发绕过办公网 8080 封锁）
- [ ] 5.4 **回滚演练**：立即用快照回滚一次并验证静态链路 → 再重新部署（证明快照真能用）
- [ ] 5.5 观察期后择期开 `remove-static-token` 提案（不在本 change）
