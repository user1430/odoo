# Tasks: remove-static-token

> 提案已经用户确认实施（2026-10-06「不要留风险/不要留垃圾」+「继续处理」）。云端步骤每步留快照。

## 1. 代码

- [x] 1.1 `auth.py` 删除 `_StaticTokenMiddleware`、`_StaticTokenMatcher`、`OAuthBearerMiddleware` 静态比对短路及 `MCP_AUTH_TOKEN` 读取；模块 docstring 同步（顺手修正：`DEFAULT_USERINFO_ENDPOINT` 默认值由废弃 copilot 切到自建 IdP `/me`）
- [x] 1.2 `build_auth_middleware` 收窄：缺省=`oauth`，仅 `oauth` 合法；`static`/`both`/其他值 ValueError（文案指明静态通道已移除）；`server.py` 缺省同步、`DEFAULT_AUTHORIZATION_SERVER` 切自建 IdP
- [x] 1.3 README 与 `.env.example` 删除 `MCP_AUTH_TOKEN`、`MCP_AUTH_MODE` 说明更新为仅 oauth（README 补 introspection/well-known 配置行）

## 2. 本地验证矩阵（`MCP_TRANSPORT=streamable-http MCP_PORT=8081`，mock introspection）

- [x] 2.1 无 Authorization 头 → 401 + `WWW-Authenticate` 挑战头 ✅
- [x] 2.2 有效 OAuth token（mock introspection `active:true`）→ initialize 202 + odoo_ping=18.0 ✅
- [x] 2.3 伪造 token → 401，60s 内复求 neg-hit ✅
- [x] 2.4 旧静态 token → **401**（本地以任意未知 token 覆盖同一路径：introspection `active:false`→401；真旧 token 云端 3.4 复验）
- [x] 2.5 `MCP_AUTH_MODE=static` / `=both` → 启动 ValueError（文案含迁移提示）；缺省 → 日志 `auth mode=oauth` ✅
- [x] 2.6 回归：`/.well-known/oauth-protected-resource/mcp` 匿名 200（AS 已指向自建 IdP）；`/authorize` 匿名 404；日志仅 sha256[:8]、原文 0 次 ✅
- 备注：测试期间发现并清理两个遗留垃圾进程（上午的 8081 旧码进程、`/tmp/odoo-mcp-fix2` 临时 venv 进程）

## 3. 云端灰度（先决：本地矩阵全绿）

- [x] 3.1 **确认静态 token 无分发**（⚠️ 审计依据修正：静态命中放行不打日志，journal 无法区分静态使用——可靠依据是持有方仅云端 unit + 用户本人，且连接器已实测走 OAuth；用户以「不要留风险」+「继续处理」明确指示执行）
- [x] 3.2 快照：`/root/backups/odoo-mcp-backup-2026-10-06-pre-rmstatic.tgz`（19M）+ `odoo-mcp.unit.bak-pre-rmstatic`（1239B）✅
- [x] 3.3 部署新码（分片 gzip+base64，三文件 md5 全对本地 18.0）+ 主 unit 删 `MCP_AUTH_TOKEN` 行（原值暂存验证后即焚，未留档）+ override.conf `MCP_AUTH_MODE=oauth` → daemon-reload + restart，启动日志 `auth mode=oauth introspection=https://odoomcp.duckdns.org/token/introspection` ✅。**顺带完成**：introspection 凭据云端轮换（新值 openssl 生成不出云，IdP .env 与 override.conf 同步）；IdP `configuration.js` 同步 env 化修正；`MCP_HOST` 0.0.0.0→127.0.0.1 真端口收敛
- [x] 3.4 云端验证全绿：旧静态 token 401（行为变更生效）✅ 无头 401 + `WWW-Authenticate` 挑战头 ✅ 伪造 token introspection `active:false`→401 ✅ well-known 200 ✅ IdP 公网 discovery 200 ✅ 443 经 Caddy 链路复验 ✅（OAuth 放行路径由 3.5 连接器实测兜底）
- [ ] 3.5 **WorkBuddy 连接器回归**（需用户配合）：连接器对话重测 odoo_ping + 列表类工具，确认无感知

## 4. 提交与归档

- [ ] 4.1 小步提交：实现 / 文档 / openspec 分开 commit
- [ ] 4.2 spec 增量合并入 `openspec/specs/mcp-auth/spec.md`，change 移入 archive（完成 add-oauth-mcp-auth 遗留 5.5）
