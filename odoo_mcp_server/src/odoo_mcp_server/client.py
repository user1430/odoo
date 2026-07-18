"""Odoo XML-RPC client for the MCP server.

Connects to a local/remote Odoo instance over the standard XML-RPC API
(endpoints /xmlrpc/2/common and /xmlrpc/2/object) and exposes thin helpers
used by the MCP tools.
"""
from __future__ import annotations

import os
import xmlrpc.client
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass
class OdooConfig:
    url: str = os.environ.get("ODOO_URL", "http://localhost:8069")
    db: str = os.environ.get("ODOO_DB", "odoo")
    username: str = os.environ.get("ODOO_USER", "admin")
    password: str = os.environ.get("ODOO_PASSWORD", "admin")
    readonly: bool = os.environ.get("ODOO_READONLY", "true").lower() in (
        "1",
        "true",
        "yes",
        "y",
    )


def _clean(value: Any) -> Any:
    """Make Odoo's XML-RPC payload JSON-serialisable for MCP."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


class OdooClient:
    def __init__(self, config: OdooConfig | None = None) -> None:
        self.config = config or OdooConfig()
        self._uid: int | None = None
        self._common = xmlrpc.client.ServerProxy(
            f"{self.config.url}/xmlrpc/2/common", allow_none=True
        )
        self._models = xmlrpc.client.ServerProxy(
            f"{self.config.url}/xmlrpc/2/object", allow_none=True
        )

    @property
    def uid(self) -> int:
        if self._uid is None:
            self._uid = self._common.authenticate(
                self.config.db, self.config.username, self.config.password, {}
            )
            if not self._uid:
                raise ConnectionError(
                    "Odoo 鉴权失败，请检查 ODOO_DB / ODOO_USER / ODOO_PASSWORD"
                )
        return self._uid

    def version(self) -> dict:
        return _clean(self._common.version())

    def execute_kw(self, model: str, method: str, args=None, kwargs=None) -> Any:
        args = list(args or [])
        kwargs = kwargs or {}
        result = self._models.execute_kw(
            self.config.db, self.uid, self.config.password, model, method, args, kwargs
        )
        return _clean(result)

    def search(self, model, domain, *, limit=50, offset=0, order=""):
        kw = {"limit": limit, "offset": offset}
        if order:
            kw["order"] = order
        return self.execute_kw(model, "search", [domain], kw)

    def search_read(self, model, domain, fields=None, *, limit=50, offset=0, order=""):
        kw = {"limit": limit, "offset": offset}
        if fields:
            kw["fields"] = fields
        if order:
            kw["order"] = order
        return self.execute_kw(model, "search_read", [domain], kw)

    def read(self, model, ids, fields=None):
        kw = {"fields": fields} if fields else {}
        return self.execute_kw(model, "read", [list(ids)], kw)

    def create(self, model, vals):
        self._require_write()
        return self.execute_kw(model, "create", [vals])

    def write(self, model, ids, vals):
        self._require_write()
        return self.execute_kw(model, "write", [list(ids), vals])

    def fields_get(self, model, attributes=None):
        return self.execute_kw(
            model, "fields_get", [], {"attributes": attributes} if attributes else {}
        )

    def _require_write(self):
        if self.config.readonly:
            raise PermissionError("当前为只读模式 (ODOO_READONLY=true)，写操作已禁用")
