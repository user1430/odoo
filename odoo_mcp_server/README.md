# Odoo 制造 MCP Server（stdio / HTTP 双模式）

把 Odoo 制造系统通过 MCP 协议接入 WorkBuddy。MCP Server 支持两种运行模式：

- **stdio（默认）**：本地进程方式运行，供本机 WorkBuddy/CodeBuddy 接入，无网络地址；
- **HTTP（streamable-http / SSE）**：对外提供 HTTP 端点，可被本机或云端 MCP 客户端调用。

无论哪种模式，MCP Server 都通过 Odoo 标准 XML-RPC 接口
（`/xmlrpc/2/common`、`/xmlrpc/2/object`）桥接业务数据。

## 架构

```
本机模式:   WorkBuddy ──MCP(stdio)──▶ odoo-mcp-server ──XML-RPC──▶ Odoo(:8069)

HTTP 模式:  本机/云端 MCP 客户端 ──HTTP──▶ odoo-mcp-server(:8080) ──XML-RPC──▶ Odoo(:8069)
```

## 安装

建议使用独立的 Python 虚拟环境（不要污染 Odoo 自己的 venv）：

```bash
cd odoo_mcp_server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 配置

通过环境变量提供连接信息（参考 `.env.example`）：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `ODOO_URL` | Odoo XML-RPC 地址 | `http://localhost:8069` |
| `ODOO_DB` | 数据库名 | `odoo` |
| `ODOO_USER` | Odoo 登录账号（建议专用最小权限账号） | `admin` |
| `ODOO_PASSWORD` | 账号密码 | `admin` |
| `ODOO_READONLY` | `true` 时禁止所有写操作 | `true` |
| `MCP_TRANSPORT` | 传输方式：`stdio` / `streamable-http` / `sse` | `stdio` |
| `MCP_HOST` | HTTP 模式监听地址（对外部署改 `0.0.0.0`） | `127.0.0.1` |
| `MCP_PORT` | HTTP 模式监听端口 | `8080` |
| `MCP_AUTH_TOKEN` | 设置后 HTTP 请求需带 `Authorization: Bearer <token>` | 空（不鉴权） |

> 安全：不要把 `odoo.conf` 里的 `admin_passwd` 当作业务账号密码；为 MCP 创建一个
> 仅具备所需模型读/写权限的 Odoo 用户，并优先保持 `ODOO_READONLY=true`。

## 在 WorkBuddy 中接入

WorkBuddy 支持自定义 MCP Server（界面或 CLI 配置）。填入如下配置（stdio 传输）：

```json
{
  "mcpServers": {
    "odoo-manufacturing": {
      "command": "/绝对路径/odoo_mcp_server/.venv/bin/odoo-mcp-server",
      "env": {
        "ODOO_URL": "http://localhost:8069",
        "ODOO_DB": "odoo",
        "ODOO_USER": "odoo_api",
        "ODOO_PASSWORD": "你的业务账号密码",
        "ODOO_READONLY": "true"
      }
    }
  }
}
```

`command` 指向 `pip install -e .` 生成的入口脚本；若直接用源码运行，可改为：

```json
{
  "mcpServers": {
    "odoo-manufacturing": {
      "command": "/绝对路径/odoo_mcp_server/.venv/bin/python",
      "args": ["-m", "odoo_mcp_server"],
      "env": { "ODOO_URL": "http://localhost:8069", "ODOO_DB": "odoo", "ODOO_USER": "odoo_api", "ODOO_PASSWORD": "xxx", "ODOO_READONLY": "true" }
    }
  }
}
```

## 对外 HTTP 部署（提供 MCP 服务地址）

### 启动

```bash
# 本机调试（仅监听回环）
MCP_TRANSPORT=streamable-http MCP_PORT=8080 odoo-mcp-server

# 局域网/对外部署：监听所有网卡 + Bearer Token 鉴权
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8080 \
MCP_AUTH_TOKEN=你的随机长Token odoo-mcp-server
```

端点地址（`MCP_TRANSPORT` 决定）：

| 传输方式 | 端点 | 说明 |
| --- | --- | --- |
| `streamable-http` | `http://<host>:<port>/mcp` | MCP 2025-03 规范，推荐 |
| `sse` | `http://<host>:<port>/sse` | 旧版传输，兼容仅支持 SSE 的客户端 |

### 客户端接入（远程 URL 方式）

支持 URL 接入的 MCP 客户端（CodeBuddy/WorkBuddy 远程 MCP、Claude 等）：

```json
{
  "mcpServers": {
    "odoo-manufacturing": {
      "url": "http://<服务器IP>:8080/mcp",
      "headers": { "Authorization": "Bearer 你的随机长Token" }
    }
  }
}
```

### 云端部署拓扑

```
云端 MCP 客户端 ──HTTPS──▶ 反向代理(TLS+鉴权) ──▶ odoo-mcp-server ──XML-RPC──▶ Odoo
```

要求与建议：

1. **Odoo 可达性**：MCP Server 部署在哪，`ODOO_URL` 就要能连到哪。两种常见做法：
   - 整套（Odoo + MCP Server）一起部署到云服务器；
   - MCP Server 留在本机，通过 frp / Tailscale / 云主机反代打通到本机 Odoo。
2. **必须加鉴权**：设置 `MCP_AUTH_TOKEN`，或在反向代理（Nginx/Caddy）层做 TLS + 认证后再放行。
3. **防火墙**：只放行反向代理端口；Odoo 的 8069 保持 `127.0.0.1` 绑定，不要直接暴露公网。

## 云端部署现状（<REGION>轻量服务器）

已在腾讯云<REGION>轻量服务器部署本 MCP Server（streamable-http 模式），数据源仍为本机 Odoo：

```
云端 MCP 客户端 ──HTTP :8080──▶ odoo-mcp(<SERVER_IP>, systemd) ──SSH隧道 :7069──▶ 本机 Odoo(:8069)
```

| 项 | 值 |
| --- | --- |
| MCP 地址 | `http://<SERVER_IP>:8080/mcp` |
| 传输方式 | `streamable-http`（Bearer Token 鉴权） |
| 云端服务 | systemd 服务 `odoo-mcp`，代码位于 `/opt/odoo-mcp-server` |
| 数据链路 | 云端 `ODOO_URL=http://127.0.0.1:7069` → SSH 反向隧道 → 本机 `127.0.0.1:8069` |
| 隧道 | 本机执行 `./ssh-tunnel-start.sh`（密钥 `~/.ssh/odoo_tunnel_ed25519`，云端仅允许端口转发） |
| 数据库 | 本机 `demo` 库（注意不是 `odoo`） |

注意事项：

- 本机关机/隧道断开时，云端 MCP 只能握手，无法读 Odoo 数据；重新 `./ssh-tunnel-start.sh` 即恢复。
- 公司办公网代理拦截对外 8080 端口（502 来自公司网关），请在家庭网络/热点下使用该地址。
- 曾尝试 frp 隧道，因公司网络对非标端口 TLS 的拦截而弃用（frps 已停止，防火墙 7000/8443 规则闲置）。
- `crm` 工具需 demo 库安装 `crm` 模块后方可使用。

## 提供的工具

通用（覆盖任意模型）：`odoo_ping` / `odoo_search` / `odoo_search_read` /
`odoo_read` / `odoo_describe_model` / `odoo_create` / `odoo_write`

制造专属：`list_production_orders`（生产工单）、`get_production_order`、
`workorder_progress`（工序进度）、`list_bom`（BOM 展开）、`stock_available`（库存可用量）、
`create_production_order`（创建工单，需关闭只读）。

CRM 专属（需先安装 `crm` 模块）：`list_leads`（线索/商机，可按 type=lead/opportunity
与 stage_id 过滤）、`get_lead`（读取单条）、`list_opportunities`（商机列表）、
`create_lead`（创建线索/商机，需关闭只读）。

## 备注

- 日志写到 stderr，避免污染 stdio 的 JSON-RPC 通道。
- Odoo 返回的时间/二进制字段已转换为可读格式再传给 WorkBuddy。
