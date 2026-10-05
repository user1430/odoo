# 项目上下文（Project Context）

## 项目目的

本项目是 **odoo-mcp-server**：一个独立的 Python MCP 服务器包，把 Odoo 的 XML-RPC 能力封装为 MCP 工具，供 WorkBuddy / CodeBuddy 等 AI 客户端查询与（受限地）写入 Odoo 制造（MRP）、CRM、库存数据。

演示目标：AI 助手通过 MCP 直接对生产工单、BOM、工序、库存、销售线索进行问答与操作。

## 仓库与运行环境

- 代码位置：`/Users/ruixin/Desktop/demo演示/odoo制造/odoo_mcp_server`（位于 Odoo 18 MRP 演示仓库内，源码在 `src/odoo_mcp_server/`，仅 `server.py` + `client.py` 两个模块）
- 上游依赖：**Odoo 18.0 Community**（父目录仓库，Docker Compose 编排，本机 `127.0.0.1:8069`，PostgreSQL `127.0.0.1:5432`，admin/admin）。本包通过 XML-RPC（`/xmlrpc/2/common`、`/xmlrpc/2/object`）连接，不修改 Odoo 本体。

## 技术栈与版本约束

- Python ≥ 3.10
- `mcp>=1.8.0,<2.0`（**硬约束**：mcp 2.x 已将 `FastMCP` 改名 `MCPServer`，直接升级会破坏 `server.py`）
- `uvicorn>=0.23.1`（HTTP 传输时承载 ASGI）
- 传输方式：`stdio`（默认）/ `streamable-http`（`/mcp`）/ `sse`（旧版兼容），由 `MCP_TRANSPORT` 决定

### 云端部署（腾讯云轻量服务器<REGION>区 `<INSTANCE_ID>`）

- MCP 公网地址：`http://<SERVER_IP>:8080/mcp`，systemd 服务 `odoo-mcp`，代码在 `/opt/odoo-mcp-server`
- 数据链路：云端 → SSH 反向隧道（`ssh-tunnel-start.sh`，密钥 `~/.ssh/odoo_tunnel_ed25519`）→ 本机 `127.0.0.1:8069`

## 配置约定

全部走环境变量，无配置文件：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MCP_TRANSPORT` | `stdio` | `stdio` / `streamable-http`（别名 `http`）/ `sse` |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8080` | HTTP 传输监听地址 |
| `MCP_AUTH_TOKEN` | 空 | 设置后启用静态 Bearer Token 中间件（**临时方案，将被 OAuth 取代**） |
| `ODOO_URL` | `http://localhost:8069` | Odoo XML-RPC 地址 |
| `ODOO_DB` | `odoo` | 数据库名（**本机/云端实际库名是 `demo`**） |
| `ODOO_USER` / `ODOO_PASSWORD` | `admin` / `admin` | Odoo 登录凭据 |
| `ODOO_READONLY` | `true` | `true` 时 `create`/`write` 类工具直接抛 `PermissionError` |

## 代码约定

- **默认只读**：一切写工具（`odoo_create`、`odoo_write`、`create_lead`、`create_production_order`）必须经 `_require_write()` 闸口。
- **MCP 工具命名**：通用工具 `odoo_*` 前缀（`odoo_search_read`、`odoo_describe_model`…）；领域工具按动作命名（`list_*` / `get_*` / `create_*` / `*_progress` / `stock_available`）。
- **XML-RPC 返回值**必须经 `client._clean()` 转换（datetime → ISO 字符串、bytes → utf-8），保证 MCP 层可 JSON 序列化。
- **鉴权中间件**是纯 ASGI 实现（`_BearerAuthMiddleware`），非 HTTP scope（lifespan 等）必须直接透传。

## 当前方向（2026-10-05 起）

**OAuth2 登录鉴权改造**：用标准 OAuth2 流程替换静态 Bearer Token（`MCP_AUTH_TOKEN`）方案。

### 跨项目协作（重要）

本改造横跨两个项目，通过 `/Users/ruixin/Desktop/demo演示/mcp-oauth.code-workspace` 组成 multi-root 工作区：

| 项目 | 路径 | 角色 |
| --- | --- | --- |
| odoo-mcp-server（本项目） | `.../odoo制造/odoo_mcp_server` | 资源服务器侧：token 校验 / 鉴权中间件改造 |
| codebuddy-oauth | `.../demo演示/codebuddyOauth` | OAuth2 客户端侧：Express 授权码流程（`/auth/login`、`/auth/callback`），对接 codebuddy.cn OAuth2 |

**互引约定**：两侧各有独立 `openspec/`。跨项目变更在两侧各建 change 提案，proposal.md 的 `## Impact` 中必须引用对侧提案路径（如 `codebuddyOauth/openspec/changes/<id>/`），任务拆分保持同步。

## 已知限制与注意事项

- **公司办公网代理拦截对外 8080 端口**（502 来自企业网关），SSH 22 放行——frp 方案已弃用，云链路只能走 SSH 隧道。
- 本机 Odoo 需先 `docker compose up -d`（依赖 Rancher Desktop）；容器停止后数据保留，恢复用 `docker compose start`。
- `demo` 库**未安装 `crm` 模块**，云端调用 `list_leads` 等 CRM 工具会报 "Object crm.lead doesn't exist"。
- Odoo 侧模型/Schema 变更不在本项目范围内（属父仓库，改后需 `-u <module>` 更新）。
