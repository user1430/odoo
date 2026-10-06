# 云端部署与运维手册

> 现网真实状态（2026-10-06 remove-static-token 割接后）。本文不含任何凭据值；凭据只存在于云端受控文件，见「配置位置」。

## 1. 架构总览

```
WorkBuddy 企业连接器（oauth2_code，平台侧自动完成授权+注入 token）
        │  HTTPS 443
        ▼
┌─────────────────── 腾讯云轻量（<REGION> <INSTANCE_ID>，<SERVER_IP>）───────────────────┐
│  Caddy 2（caddy.service，80/443，自动证书）                                            │
│    ├─ odoomcpdemo.duckdns.org → 127.0.0.1:8080（改写 Host，见 6.1）   → odoo-mcp      │
│    └─ odoomcp.duckdns.org     → 127.0.0.1:3000                        → odoo-idp      │
│                                                                                       │
│  odoo-mcp（odoo-mcp.service，/opt/odoo-mcp-server）                                   │
│    - 仅监听 127.0.0.1:8080；OAuth-only（introspection 优先）                           │
│    - ODOO_URL=http://127.0.0.1:7069 ──SSH 反向隧道──▶ 本机 Odoo(127.0.0.1:8069, demo库)│
│                                                                                       │
│  odoo-idp（odoo-idp.service，/opt/odoo-idp/server，node-oidc-provider v9）            │
│    - 仅监听 127.0.0.1:3000；签发/校验 token（/token/introspection 供 odoo-mcp 校验）   │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

数据链路依赖**两条隧道**（演示前必检）：
1. 云端读 Odoo 数据：本机执行 `./ssh-tunnel-start.sh`（云端 7069 → 本机 8069；密钥 `~/.ssh/odoo_tunnel_ed25519`，云端侧 restrict,port-forwarding）。
2. 本机调试云端 MCP：办公网封 8080 出方向，`ssh -N -L 18080:127.0.0.1:8080 root@<SERVER_IP>` 后访问 `http://127.0.0.1:18080/mcp`。

隧道断开时：MCP 握手与鉴权正常，但 Odoo 工具调用报错（不影响 IdP）。

## 2. 组件与配置位置

| 组件 | 代码 | 服务配置 | 凭据位置（chmod 600，勿外传） |
| --- | --- | --- | --- |
| odoo-mcp | `/opt/odoo-mcp-server` | 主 unit `/etc/systemd/system/odoo-mcp.service` + drop-in `…/odoo-mcp.service.d/override.conf` | introspection 凭据在 override.conf |
| odoo-idp | `/opt/odoo-idp/server` | systemd `odoo-idp.service` | `/opt/odoo-idp/server/.env`（登录口令/客户端 secret/JWKS 私钥/introspection 凭据） |
| Caddy | — | `/etc/caddy/Caddyfile` | 证书由 Caddy 自动管理 |

odoo-mcp 关键 env（override.conf）：`MCP_AUTH_MODE=oauth`、`OAUTH_INTROSPECTION_ENDPOINT=https://odoomcp.duckdns.org/token/introspection`、`OAUTH_INTROSPECTION_CLIENT_ID/SECRET`、`OAUTH_USERINFO_ENDPOINT`（兜底）、`OAUTH_AUTHORIZATION_SERVER`。主 unit 含 `MCP_HOST=127.0.0.1`、`ODOO_*`。**`MCP_AUTH_TOKEN` 已废除**（静态通道移除，原值未留档）。

## 3. 防火墙（轻量控制台层）

| 端口 | 用途 | 备注 |
| --- | --- | --- |
| 22 | SSH（隧道+管理） | 保留 |
| 80/443 | Caddy | 唯一业务入口 |
| ~~8080~~ | 历史直连 | **死规则，待删**：服务已绑 127.0.0.1，公网本不可达 |
| 7000/8443 | frp 既有设施 | 闲置未动 |

## 4. 日志

| 内容 | 位置 |
| --- | --- |
| 鉴权判定（allow/deny、pos/neg-hit、时延；token 仅 sha256[:8]） | `journalctl -u odoo-mcp` |
| IdP 登录/签发/模拟短信码 | `journalctl -u odoo-idp` |
| HTTP 访问日志（含 client_ip，10MB×5 滚动） | `/var/log/caddy/mcp-access.log`、`/var/log/caddy/idp-access.log` |

## 5. 备份与回滚

全部集中于 **`/root/backups/`**，详见 `MANIFEST.md`。要点：

- 当前回滚位 = pre-rmstatic 快照（both 模式代码 + unit + override.conf）。
- ⚠️ 回滚 both 模式须**重新生成**静态 token 写入主 unit（原值已按「凭据不留档」原则销毁），并 `daemon-reload && restart`。
- copilot 时代的备份已标注「勿回滚」（IdP 已完全替换）。

## 6. 故障排查速查

### 6.1 421 Invalid Host header
FastMCP 默认只认 loopback Host（DNS-rebinding 保护）。域名访问必须经 Caddy（`header_up Host 127.0.0.1:8080` 统一改写）。若未来改域名直连 8080，需在 server.py 给 FastMCP 传 `transport_security` 显式放行。

### 6.2 401
- 无/错 token → 正常拒绝（响应带 `WWW-Authenticate` 挑战头，MCP 客户端据此走 OAuth 发现）。
- 真 token 也 401 → 查 `journalctl -u odoo-idp` 是否在线、`/var/log/caddy/idp-access.log` introspection 请求是否到达。

### 6.3 503 auth_unavailable
IdP 故障/不可达（区别于 401）。重启 `odoo-idp` 并查其日志。

### 6.4 IdP 重启的已知影响
内存态：DCR 动态客户端与进行中的登录会话丢失（已签发 token 因 JWKS 固定仍可验）。WorkBuddy 桌面端会自动重新走 OAuth；连接器用静态 client，不受影响。

### 6.5 凭据轮换（如疑似泄露）
1. 云端 `openssl rand -hex 32` 生成新值；
2. 同步两处：IdP `/opt/odoo-idp/server/.env` 与 odoo-mcp override.conf；
3. `systemctl restart odoo-idp odoo-mcp`；连接器侧 secret 变更还需在企业后台同步。

## 7. 常用命令

```bash
systemctl status odoo-mcp odoo-idp caddy     # 服务状态
journalctl -u odoo-mcp -f                    # 鉴权日志
systemctl restart odoo-mcp                   # 重启（秒级）
md5sum /opt/odoo-mcp-server/src/odoo_mcp_server/*.py   # 与本地 18.0 分支对版
```
