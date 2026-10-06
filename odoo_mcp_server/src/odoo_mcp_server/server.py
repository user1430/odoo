"""MCP server exposing Odoo manufacturing operations.

传输方式由环境变量 MCP_TRANSPORT 决定：
- stdio（默认）：本机子进程方式运行，供 WorkBuddy/CodeBuddy 本地接入；
- streamable-http：对外提供 HTTP 端点（/mcp），可被云端 MCP 客户端调用；
- sse：旧版 HTTP 传输（/sse + /messages/），兼容只支持 SSE 的客户端。
"""
from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from .client import OdooClient

mcp = FastMCP("odoo-manufacturing")
client = OdooClient()


@mcp.tool()
def odoo_ping() -> dict:
    """测试与 Odoo 的连接并返回服务器版本信息。"""
    return {"connected": True, "version": client.version()}


@mcp.tool()
def odoo_search(
    model: str, domain: list, limit: int = 50, offset: int = 0, order: str = ""
) -> list:
    """在任意 Odoo 模型中按条件搜索，返回记录 ID 列表。

    :param model: 模型名，例如 "mrp.production"
    :param domain: Odoo 域表达式，例如 [["state","=","confirmed"]]
    :param limit/offset/order: 分页与排序
    """
    return client.search(model, domain, limit=limit, offset=offset, order=order)


@mcp.tool()
def odoo_search_read(
    model: str,
    domain: list,
    fields: list | None = None,
    limit: int = 50,
    offset: int = 0,
    order: str = "",
) -> list:
    """搜索并直接读取字段，返回记录字典列表（比先 search 再 read 更高效）。"""
    return client.search_read(
        model, domain, fields, limit=limit, offset=offset, order=order
    )


@mcp.tool()
def odoo_read(model: str, ids: list, fields: list | None = None) -> list:
    """按 ID 列表读取指定模型的记录。"""
    return client.read(model, ids, fields)


@mcp.tool()
def odoo_describe_model(model: str, attributes: list | None = None) -> dict:
    """返回模型的字段定义（fields_get），用于先了解可用字段，再做查询/写入。"""
    return client.fields_get(model, attributes)


@mcp.tool()
def odoo_create(model: str, vals: dict) -> int:
    """在任意 Odoo 模型中创建一条记录。要求 ODOO_READONLY=false。"""
    return client.create(model, vals)


@mcp.tool()
def odoo_write(model: str, ids: list, vals: dict) -> bool:
    """更新指定 ID 的记录。要求 ODOO_READONLY=false。"""
    return client.write(model, ids, vals)


# ---------- CRM 专属工具 ----------

_LEAD_FIELDS = [
    "name",
    "type",
    "contact_name",
    "email_from",
    "phone",
    "partner_id",
    "user_id",
    "team_id",
    "stage_id",
    "probability",
    "expected_revenue",
    "date_deadline",
    "priority",
]


@mcp.tool()
def list_leads(type: str = "", stage_id: int | None = None, limit: int = 20) -> list:
    """查询销售线索/商机 (crm.lead)。type 可留空，或 lead(线索)/opportunity(商机)；stage_id 为阶段 ID。"""
    domain: list = []
    if type:
        domain.append(["type", "=", type])
    if stage_id is not None:
        domain.append(["stage_id", "=", stage_id])
    return client.search_read(
        "crm.lead", domain, _LEAD_FIELDS, limit=limit, order="id desc"
    )


@mcp.tool()
def get_lead(lead_id: int) -> dict:
    """读取单条销售线索/商机 (crm.lead) 的完整信息。"""
    recs = client.read("crm.lead", [lead_id])
    return recs[0] if recs else {}


@mcp.tool()
def list_opportunities(stage_id: int | None = None, limit: int = 20) -> list:
    """查询商机 (crm.lead, type=opportunity)，可按 stage_id 过滤。"""
    domain = [["type", "=", "opportunity"]]
    if stage_id is not None:
        domain.append(["stage_id", "=", stage_id])
    return client.search_read(
        "crm.lead", domain, _LEAD_FIELDS, limit=limit, order="id desc"
    )


@mcp.tool()
def create_lead(
    name: str,
    type: str = "lead",
    contact_name: str = "",
    email_from: str = "",
    phone: str = "",
    user_id: int | None = None,
    team_id: int | None = None,
    expected_revenue: float = 0.0,
    stage_id: int | None = None,
) -> int:
    """创建一条销售线索/商机 (crm.lead)。要求 ODOO_READONLY=false。"""
    vals: dict = {"name": name, "type": type}
    if contact_name:
        vals["contact_name"] = contact_name
    if email_from:
        vals["email_from"] = email_from
    if phone:
        vals["phone"] = phone
    if user_id is not None:
        vals["user_id"] = user_id
    if team_id is not None:
        vals["team_id"] = team_id
    if expected_revenue:
        vals["expected_revenue"] = expected_revenue
    if stage_id is not None:
        vals["stage_id"] = stage_id
    return client.create("crm.lead", vals)


# ---------- 制造专属工具 ----------


@mcp.tool()
def list_production_orders(state: str = "", limit: int = 20) -> list:
    """查询生产工单 (mrp.production)。state 可留空或 confirmed/progress/done/cancel。"""
    domain = [["state", "=", state]] if state else []
    return client.search_read(
        "mrp.production",
        domain,
        ["name", "product_id", "product_qty", "state", "date_start", "bom_id"],
        limit=limit,
        order="id desc",
    )


@mcp.tool()
def get_production_order(mo_id: int) -> dict:
    """读取单个生产工单 (mrp.production) 的完整信息。"""
    recs = client.read("mrp.production", [mo_id])
    return recs[0] if recs else {}


@mcp.tool()
def workorder_progress(mo_id: int) -> list:
    """返回某生产工单下的工序 (mrp.workorder) 进度：已生产/计划数量与状态。"""
    return client.search_read(
        "mrp.workorder",
        [["production_id", "=", mo_id]],
        ["name", "workcenter_id", "state", "qty_produced", "qty_production"],
    )


@mcp.tool()
def list_bom(product_id: int | None = None, bom_id: int | None = None) -> list:
    """展开物料清单 (mrp.bom) 的明细行：子件、用量、单位。可传 product_id 或 bom_id。"""
    if bom_id:
        domain = [["id", "=", bom_id]]
    elif product_id:
        domain = [["product_id", "=", product_id], ["active", "=", True]]
    else:
        return []
    boms = client.search_read(
        "mrp.bom", domain, ["product_id", "product_qty", "product_uom_id"]
    )
    for b in boms:
        b["lines"] = client.search_read(
            "mrp.bom.line",
            [["bom_id", "=", b["id"]]],
            ["product_id", "product_qty", "product_uom_id"],
        )
    return boms


@mcp.tool()
def stock_available(product_id: int) -> dict:
    """查询某产品的可用库存：累计现有量、已保留量与理论可用量 (stock.quant)。"""
    rows = client.execute_kw(
        "stock.quant",
        "read_group",
        [
            [["product_id", "=", product_id]],
            ["quantity:sum", "reserved_quantity:sum"],
            ["product_id"],
        ],
    )
    return (
        rows[0]
        if rows
        else {"product_id": product_id, "quantity": 0, "reserved_quantity": 0}
    )


@mcp.tool()
def create_production_order(
    product_id: int, qty: float, bom_id: int | None = None
) -> int:
    """创建一张生产工单 (mrp.production)。要求 ODOO_READONLY=false。"""
    vals = {"product_id": product_id, "product_qty": qty}
    if bom_id:
        vals["bom_id"] = bom_id
    return client.create("mrp.production", vals)


def _resolve_transport() -> str:
    raw = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
    return {"http": "streamable-http", "streamable_http": "streamable-http"}.get(
        raw, raw
    )


def _run_http(transport: str) -> None:
    import uvicorn

    from .auth import build_auth_middleware

    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8080"))
    mode = os.environ.get("MCP_AUTH_MODE", "both")

    app = mcp.sse_app() if transport == "sse" else mcp.streamable_http_app()
    app = build_auth_middleware(app, mode)  # type: ignore[assignment]

    logging.getLogger("odoo_mcp").info(
        "MCP server listening on http://%s:%s (transport=%s, auth_mode=%s)",
        host,
        port,
        transport,
        mode.strip().lower(),
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s odoo_mcp: %(message)s",
    )
    transport = _resolve_transport()
    if transport in ("sse", "streamable-http"):
        _run_http(transport)
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
