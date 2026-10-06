# Design: remove-static-token

## Context

`add-oauth-mcp-auth` 引入 `MCP_AUTH_MODE=static|oauth|both` 三态，both 为过渡回滚位。阶段 3 云端灰度（5.1-5.4）与公网 HTTPS（Caddy 443 → 127.0.0.1:8080）上线后，企业连接器已全流程走 OAuth（授权码 + PKCE + RFC 8707 resource → aud token → introspection 校验）。静态 token 自灰度起零使用。

现网事实（2026-10-06 实测）：
- odoo-mcp 仅监听 `127.0.0.1:8080`，公网唯一入口为 Caddy 443（`odoomcpdemo.duckdns.org`）；
- `MCP_AUTH_TOKEN` 写在主 unit `/etc/systemd/system/odoo-mcp.service`（override.conf 只有 OAuth 配置）；
- 7 天 journal：`static allow=0`、`oauth allow=75`、`deny=7`。

## Goals & Non-Goals

- Goals：删除静态 token 通道与其凭据；配置面 fail-fast；spec 一步对齐现网。
- Non-Goals：不改 OAuth 校验逻辑本身；不动 IdP/Caddy/工具层；不做 stdio 鉴权。

## Decisions

- **D1：`MCP_AUTH_MODE` 收窄为仅 `oauth`，而非删除该变量。** 保留变量可在云端残留 `static`/`both` 配置时启动 fail-fast（ValueError 文案指明已移除），把配置漂移变成显式错误；若删变量，残留配置会被静默忽略，服务以 oauth 启动但无人察觉。
- **D2：静态代码删除，不保留死代码。** both 是过渡回滚设计，观察期已结束；保留 `_StaticTokenMatcher` 等于保留凭据比对面与误配放行的可能。回滚靠 git 与快照，不靠开关。
- **D3：introspection 与 well-known 两项已上线能力随本 change 补登 spec。** 二者随 commit ba7668da7fa 灰度上线但基线 spec 未收录；与 REMOVED 静态行为一并在归档时合并，避免 spec 再次滞后。
- **D4：云端先快照再动 unit。** 沿用 add-oauth-mcp-auth 5.1 快照机制与 5.4 已验证的回滚演练；主 unit 与 override.conf 同一维护窗口内修改 + daemon-reload + restart。

## Risks

| 风险 | 缓解 |
| --- | --- |
| 未知存量静态客户端被 401 | 7 天审计为 0；执行前拉长到 14 天复核（tasks 3.1） |
| 改 unit 后服务起不来 | fail-fast 文案 + 快照秒级回滚（已演练） |
| OAuth 单点（IdP 故障） | 既有降级策略：有正缓存放行，否则 503 明确区分 IdP 故障；非本 change 新增 |
