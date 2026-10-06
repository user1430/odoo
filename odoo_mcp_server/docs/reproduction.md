# 本地复现与借用指南

三条路径：**A. 纯本地复现**（不依赖我的云端，推荐）；**B. 借用我的云端环境**；**C. 混合**（本地 Odoo + 云端 IdP/MCP，即我自己的日常形态，见 deployment.md）。

> 凭据边界：所有 secret 只进 `.env`（git 已忽略），`.env.example` 全为占位符。不要向任何人索要/发送真实凭据值。

## A. 纯本地复现

### A.1 启动 Odoo 18（数据源）

父目录 Odoo 仓库（docker-compose 编排）：启动后 Web 在 `http://127.0.0.1:8069`，数据库名 `demo`（注意不是 `odoo`），初始账号 `admin/admin`。

### A.2 启动 IdP（OAuth 授权服务器）

```bash
cd oauthDemo/server
npm install
cp .env.example .env      # 然后按下表填值
npm start                 # 默认 127.0.0.1:3000
```

`.env` 必填项（本地值可随意，强度无要求）：

| 变量 | 本地复现填法 |
| --- | --- |
| `ISSUER` | `http://localhost:3000`（必须与访问地址完全一致） |
| `CLIENT_ID` / `CLIENT_SECRET` | 连接器静态客户端凭据，如 `local-connector` / 随机串 |
| `REDIRECT_URI` | 先用 WorkBuddy 建连接器拿到回调 URL 再填（本地自测可不填） |
| `ADMIN_PASSWORD` / `DEMO_USER_PASSWORD` | 账密兜底登录的口令（演示账号 admin / demo） |
| `JWKS_JSON` | 执行 `node scripts/gen-jwks.mjs`，把输出整行贴入 |
| `MCP_RESOURCE_CLIENT_SECRET` | 随机串，与下方 odoo-mcp 侧保持一致 |
| `DEMO_ECHO_SMS_CODE` | `true`（模拟短信码直接回显在登录页） |

### A.3 启动 odoo-mcp（资源服务器）

```bash
cd odoo_mcp_server
python3 -m venv .venv && .venv/bin/pip install -e .
env MCP_TRANSPORT=streamable-http MCP_PORT=8080 \
    ODOO_URL=http://127.0.0.1:8069 ODOO_DB=demo ODOO_USER=admin ODOO_PASSWORD=admin \
    OAUTH_INTROSPECTION_ENDPOINT=http://127.0.0.1:3000/token/introspection \
    OAUTH_INTROSPECTION_CLIENT_ID=mcp-resource-server \
    OAUTH_INTROSPECTION_CLIENT_SECRET=<与 IdP .env 相同> \
    .venv/bin/odoo-mcp-server
# 启动日志应见：auth mode=oauth introspection=...
```

### A.4 验证清单

```bash
curl -i http://127.0.0.1:8080/mcp                       # 401 + WWW-Authenticate
curl http://127.0.0.1:8080/.well-known/oauth-protected-resource/mcp   # 200 资源元数据
```

完整授权码流程：浏览器打开 IdP 自测页 `http://127.0.0.1:3000/client` → 手机号+模拟码（页面回显）或账密登录 → 授权 → 拿回 token 后 `curl -H "Authorization: Bearer <token>" http://127.0.0.1:8080/mcp`（initialize 应 200，`tools/call odoo_ping` 返回 18.0）。

### A.5 接入 WorkBuddy（本地）

WorkBuddy 企业后台建 oauth2_code 连接器：MCP URL 填本机可达地址（如内网穿透域名）；客户端可走 DCR 自动注册（IdP 对 loopback 与 `www.codebuddy.cn` 回调开放），或静态填 A.2 的 `CLIENT_ID/SECRET`。Scopes：`openid profile email`，User Info Name Path：`name`。

## B. 借用我的云端环境

1. 拿到演示账号说明后，在你自己的 WorkBuddy 建 oauth2_code 连接器：
   - MCP URL：`https://odoomcpdemo.duckdns.org/mcp`
   - 授权/令牌端点：`https://odoomcp.duckdns.org/auth`、`/token`（DCR 开放，可自动注册）
2. 授权时走登录页：**手机号 + 模拟验证码**（验证码直接回显在页面上，纯演示、不代表真实身份），或账密兜底。
3. 数据源是我本机的演示 Odoo（制造/CRM 演示数据）——我读你共享前会确认隧道在线；**只读演示，勿依赖持久性**。
4. 出问题时按 deployment.md 第 6 节自查，或把 `journalctl -u odoo-mcp` 时间戳发我。

## C. 混合（我的日常形态）

云端 IdP + 云端 odoo-mcp + SSH 反向隧道回本机 Odoo。配置与故障排查全部见 [deployment.md](deployment.md)。
