# Odoo 制造 MCP Server（同机 stdio 部署）

把 Odoo 制造系统通过 MCP 协议接入 WorkBuddy。MCP Server 作为本地进程运行，
通过 Odoo 标准 XML-RPC 接口（`/xmlrpc/2/common`、`/xmlrpc/2/object`）桥接业务数据。

## 架构

```
WorkBuddy ──MCP(stdio)──▶ odoo-mcp-server ──XML-RPC──▶ Odoo(:8069)
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

## 提供的工具

通用（覆盖任意模型）：`odoo_ping` / `odoo_search` / `odoo_search_read` /
`odoo_read` / `odoo_describe_model` / `odoo_create` / `odoo_write`

制造专属：`list_production_orders`（生产工单）、`get_production_order`、
`workorder_progress`（工序进度）、`list_bom`（BOM 展开）、`stock_available`（库存可用量）、
`create_production_order`（创建工单，需关闭只读）。

## 备注

- 日志写到 stderr，避免污染 stdio 的 JSON-RPC 通道。
- Odoo 返回的时间/二进制字段已转换为可读格式再传给 WorkBuddy。
