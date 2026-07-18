# CODEBUDDY.md This file provides guidance to CodeBuddy when working with code in this repository.

This is a local deployment of **Odoo 18.0** (the framework source + community addons) focused on the **Manufacturing (MRP)** business modules, run via Docker and exposed to AI assistants through a read-only MCP server.

## Common commands

**Start the application stack.** Brings up Odoo and PostgreSQL from `docker-compose.yml`; the repo root is mounted into the container so source edits are live. Odoo becomes reachable at `127.0.0.1:8069`, PostgreSQL at `127.0.0.1:5432`. Admin password is `admin`.
```bash
docker-compose up -d --build
```

**Tail Odoo logs.** Follows the Odoo service log stream inside the container (useful after a restart or module update).
```bash
docker-compose logs -f odoo
```

**Install or update a module.** Inside the running container, `-i` installs and `-u` upgrades a module (e.g. `mrp`); `--stop-after-init` runs the operation then exits. The database (default `odoo`) must already exist.
```bash
docker compose exec odoo python odoo-bin -c /etc/odoo/odoo.conf -d odoo -u mrp --stop-after-init
```

**Run a module's test suite.** Enables tests and updates the module; all `tests/` cases tagged `standard` run. Requires the database to exist. Use `-i` instead of `-u` for a freshly created DB.
```bash
docker compose exec odoo python odoo-bin -c /etc/odoo/odoo.conf -d odoo --test-enable --stop-after-init -u mrp
```

**Run a single test.** `--test-tags` selects by class, method, or module path; `+standard`/`-standard` adjust tag filters. Runs inside the container.
```bash
docker compose exec odoo python odoo-bin -c /etc/odoo/odoo.conf -d odoo --test-enable --stop-after-init -u mrp --test-tags ':TestMrpProduction.test_basic'
```

**Open an interactive shell.** Drops into an Odoo `ipython`/`python` shell bound to the database's `Environment` (`self.env` available). Handy for poking at MRP models directly.
```bash
docker compose exec odoo python odoo-bin shell -c /etc/odoo/odoo.conf -d odoo
```

**Run the framework linter.** Odoo lin ts itself via the `test_lint` module (runs `flake8` per `setup.cfg` plus Odoo-specific checks). Trigger it like a test suite; `--test-tags` can narrow to one file.
```bash
docker compose exec odoo python odoo-bin -c /etc/odoo/odoo.conf -d odoo --test-enable --stop-after-init -u test_lint
```

## Architecture

Odoo has a **two-tier layout**: the framework package lives in `odoo/` while business modules live in `addons/`. A running instance loads modules on top of the framework; almost everything an application does is a record manipulated through the ORM.

### Module structure (the unit of extension)
Each module under `addons/xxx/` is a Python package whose `__manifest__.py` declares `name`, `depends`, `data`, `installable`, `application`, and (optionally) `assets`, `qweb`, `license`. Code is organized by convention into `models/` (Python `Model` subclasses), `views/*.xml` (UI definitions), `security/` (`ir.model.access.csv` + record rules), `data/*.xml` (seed/demo data), `controllers/` (`http.Controller` subclasses for web routes), `wizard/` (transient models), `report/` (QWeb/PDF), and `tests/`. To add a field you edit `models/`; to expose it you add `views/*.xml` and register the file in the manifest's `data`.

### ORM layer (`odoo/api.py`, `odoo/models.py`, `odoo/fields.py`)
All data access goes through `odoo.models.Model` subclasses. An `Environment` (`env`) bundles a DB cursor (`cr`), user id (`uid`), and `context`, and is the factory for recordsets. Key concepts: **recordsets** (immutable sets of same-model records, behave like a list), **computed/related/stored fields**, and decorators in `odoo/api.py` — `@api.model` (no record needed), `@api.depends` (recompute trigger), `@api.onchange`, `@api.constrains`. `fields.py` defines field types and the `@api.depends` recompute engine. CRUD always funnels through `create`/`write`/`read`/`unlink`, which fire ORM hooks, compute fields, and constraints. Direct SQL is rare and belongs in `odoo/sql_db.py` cursors only.

### Module loading & registry (`odoo/modules/`)
At startup `odoo.modules.loading` resolves the dependency graph from each module's `depends`, then in topological order loads Python models into a **registry** (`odoo/modules/registry.py`, keyed by database) and parses data files via `odoo/tools/convert.py` (XML/CSV → `ir.model.data` records). This is why adding a model requires both the Python class and a manifest `data` entry for its views/access rights. The registry is per-database and rebuilt on schema changes.

### HTTP & RPC (`odoo/http.py`, `odoo/service/`)
The web app is a WSGI application built by `odoo.service.wsgi`. Web controllers decorate methods with `@http.route` (see `odoo/addons/web`, `odoo/addons/base`). External/automation access uses two RPC interfaces defined in `odoo/addons/base/controllers/rpc.py`: **JSON-RPC** at `/jsonrpc` and **XML-RPC** at `/xmlrpc/2/<service>`. The `<service>` names are `object` (→ `odoo.service.model.execute_kw`, the generic model-call entry point used by the MCP bridge), `common`, `db`, and `report`. `odoo/osv/expression.py` parses search **domains** (`[('state','=','confirmed')]`) into SQL.

### Server & process model (`odoo/service/server.py`)
`odoo-bin` calls `odoo.service.server.start()`. The default `prefork` mode spawns worker processes (set by `--workers`); `gevent`/`evented` modes exist for high-concurrency Comet/long-polling. A subset of workers are reserved as **cron workers** (`--max-cron-threads`) that execute `ir.cron` jobs. This matters when debugging: long operations or stuck workers show up per-process in logs.

### Database layer (`odoo/sql_db.py`)
A `ConnectionPool` manages `psycopg` connections per database with cursor context managers. The ORM owns transaction boundaries — a cursor commit happens at the end of an RPC call or `with env.cr.savepoint()`. Never commit manually inside model code.

### Testing (`odoo/tests/`)
Test cases subclass `TransactionCase` (one transaction per test, rolled back), `SingleTransactionCase`, or `HttpCase` (full HTTP + JS tour support, used for UI tours). Decorate with `@tagged('standard')` (default) or `post_install`/`external`. Tests live in `tests/` and run only when their module is installed/updated with `--test-enable`. `--test-tags` uses a selector (`+standard`, `:Class.method`, `/module`) — see `odoo/tests/tag_selector.py` and `odoo/tools/config.py`.

### Manufacturing domain (`addons/mrp` and siblings)
`addons/mrp` is the MRP module and the demo's focus. It depends on `stock`, `product`, `procurement`, `uom`, `calendar`, `resource`, `barcodes`. Core models: `mrp.bom` (bill of materials), `mrp.production` (manufacturing order), `mrp.routing`/`mrp.workorder` (shop-floor operations), and the linkage to `stock.move` for component consumption/finished-goods receipt. Related modules present: `mrp_subcontracting`, `mrp_repair`, `mrp_account` (WIP valuation), and `stock`. Manufacturing orders drive procurement and inventory moves, so changes here ripple into `stock` and `mrp_account`. Note: `quality` is an **Odoo Enterprise** module and is **NOT bundled** in this community repo.

### CRM module (installed)
`addons/crm` is installed and wired into the MCP server. Core model `crm.lead` unifies leads and opportunities (distinguished by the `type` field: `lead` vs `opportunity`); `crm.stage` is the pipeline stage and `crm.team` the sales team. Leads convert into `sale.order` (Sales) when won. Queried via the MCP tools `list_leads` / `get_lead` / `list_opportunities` / `create_lead` (write requires `ODOO_READONLY=false`).

### AI integration layer (`odoo_mcp_server/`)
This is a **separate Python package**, not part of Odoo. It is a stdio MCP server (`odoo_mcp_server/src/odoo_mcp_server/`) that bridges AI clients (WorkBuddy/CodeBuddy) to Odoo via XML-RPC `object.execute_kw` on `127.0.0.1:8069`. It is **config-driven (env vars) and defaults to read-only** — it queries MRP/stock/**CRM** models rather than mutating them. Treat it as the external integration boundary; modifying Odoo business logic does not require touching it.

### Deployment (`docker-compose.yml`, `Dockerfile`)
Odoo + PostgreSQL run in containers; the repo root mounts at `/odoo` so `addons/` → `/odoo/addons` and `odoo/` → `/odoo/odoo/addons` (the `addons_path` in `odoo.conf`). Port `8069` is bound to `127.0.0.1` only. `data/` holds filestore volumes. Restarting the stack picks up source edits; schema/model changes require a module update (`-u`).
