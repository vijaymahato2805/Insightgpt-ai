# InsightGPT AI

InsightGPT AI is an enterprise natural language analytics workspace for SQL Server, Dynamics NAV, and Business Central reporting data. The current implementation covers **Phases 1 through 4**: authenticated workspace, encrypted SQL Server connection management, NAV/Business Central metadata and terminology, permission-checked Text-to-SQL, and live dynamic dashboards.

## Included

- Dark, responsive React + Vite + TypeScript workspace with protected routes and sign-in.
- FastAPI API with login, logout, current-user, health, and system-status endpoints.
- PostgreSQL-backed SQLAlchemy user model and Alembic migration.
- Argon2 password hashing, JWT validation, role claims, and token-version revocation on logout.
- OpenRouter-compatible async provider adapter, task-specific model settings, fallback list, and a model registry.
- Administrator-managed SQL Server connections using SQLAlchemy and pyodbc, encrypted SQL credentials, SQL Server / Windows authentication, connection testing, and per-database user grants.
- Schema discovery for tables, views, columns, primary keys, foreign keys, indexes, and relationships; editable table/column descriptions.
- Optional NAV / Business Central `Field` and `Object` metadata caption lookup plus inferred company-specific `Company$Table` mappings.
- Company mapping and business dictionary CRUD APIs and management screens.
- OpenRouter-powered intent detection, bounded schema selection, scoped terminology retrieval, SQL generation/correction, and SQL explanation.
- SQLGlot T-SQL validation, database/company table and column allowlists, revalidation before execution, read-only query execution, result caps, query timeout, and complexity limits.
- AI Workspace UI with SQL preview and a separate run action; database credentials remain server-side and are never sent to OpenRouter.
- LLM-planned dashboard JSON validated by strict Pydantic contracts, with each widget backed by generated, revalidated, executed SQL results.
- Responsive KPI cards, Apache ECharts bar/line/area/pie/donut charts, data tables, result-derived filters, and chart/table cross-filter drill-down.
- Docker Compose services for PostgreSQL, API, and an Nginx-served frontend.
- Backend API tests using SQLite and mocked SQL Server metadata; they need neither a live SQL Server nor OpenRouter key.

## Requirements

- Docker Desktop with Compose v2
- Python 3.12+ for local backend development
- Node.js 20+ and npm 10+ for local frontend development
- Microsoft ODBC Driver 18 for SQL Server for local SQL Server connections (the API container installs it)

## Start with Docker Compose

From the repository root:

```powershell
Copy-Item .env.example .env
# Edit .env and set unique POSTGRES_PASSWORD, JWT_SECRET_KEY, and ENCRYPTION_KEY values.
docker compose up --build
```

Open `http://localhost:5173`. The API is at `http://localhost:8000`, with interactive API documentation at `http://localhost:8000/docs`.

To create the first administrator, set both `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` in `.env` before starting. The API creates the user if that email does not already exist. Clear those bootstrap values after the account is created. There is no hardcoded default login.

To stop the services, run `docker compose down`. To also remove the local PostgreSQL volume, run `docker compose down -v`.

## Run locally

### Backend

In a Python 3.12+ environment:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
$env:DATABASE_URL = "postgresql+psycopg://insightgpt:your-password@localhost:5432/insightgpt"
$env:JWT_SECRET_KEY = "replace-with-a-random-secret-at-least-32-characters-long"
$env:ENCRYPTION_KEY = "replace-with-a-separate-random-secret-at-least-32-characters-long"
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

Set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` before starting the API if you want a local admin account. PostgreSQL must be running and the database in `DATABASE_URL` must exist.

### Frontend

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Vite serves the UI at `http://localhost:5173`; `VITE_API_BASE_URL` defaults to `http://localhost:8000/api`.

## Deploy the frontend to Vercel

This repository is a full-stack application. Vercel can host the static React/Vite frontend; the API, PostgreSQL database, and Microsoft ODBC Driver 18 for SQL Server need a backend host that supports the project's Docker deployment and can reach the SQL Server instance.

1. Import this repository into Vercel and set the project Root Directory to `frontend`.
2. Use the Vite framework preset, build command `npm run build`, and output directory `dist`.
3. Set `VITE_API_BASE_URL` to the HTTPS API origin ending in `/api`, for example `https://api.example.com/api`. This value is embedded in the browser bundle, so it must contain no secrets.
4. On the API host, set `FRONTEND_ORIGINS` to the exact Vercel production origin (and any preview origins you intend to allow), then configure the production PostgreSQL, JWT, encryption, OpenRouter, and SQL Server settings from the section below.

The included `frontend/vercel.json` routes browser paths back to the SPA entry point. Deploying only this Vercel project does not deploy the API or its databases.

## Configuration

Copy `.env.example` and set secrets for the environment. Compose builds its internal PostgreSQL URL from `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`; the `DATABASE_URL` in the example is for a locally run API. Never commit `.env`, database credentials, or API keys. The OpenRouter key is read by the backend only and is never sent to the browser. To use Text-to-SQL and dashboards, set `OPENROUTER_API_KEY`, `SQL_MODEL`, `REASONING_MODEL`, and `FAST_MODEL` to IDs registered for their tasks in `config/model_registry.json`. The SQL model generates/corrects queries, the reasoning model detects intent, explains SQL, and plans dashboards, and the fast model selects relevant schema. The provider uses the configured bounded fallback chain. The `/api/system/status` endpoint reports provider readiness without returning secrets.

Generate an encryption key with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and set it as `ENCRYPTION_KEY`. It must be at least 32 characters. SQL Server usernames and passwords are Fernet-encrypted before they reach PostgreSQL and are omitted from API responses and logs. Keep this key in the deployment secret store and back it up securely; changing it makes previously saved SQL credentials unreadable. Windows / integrated authentication stores no username or password. Use a dedicated read-only SQL Server account. The API enables TLS encryption and does not trust self-signed server certificates by default; only set `SQLSERVER_TRUST_SERVER_CERTIFICATE=true` for environments where that is intentional.

The API uses a SameSite=Lax HttpOnly authentication cookie. Set `COOKIE_SECURE=true` behind HTTPS in production, and set `FRONTEND_ORIGINS` to the exact trusted frontend origins. Production requires strong, unique JWT, encryption, and PostgreSQL secrets. Administrators can manage connections and metadata; analyst/viewer access is limited to databases explicitly granted to their user. Query routes recheck database grants and company scope. Every generated and submitted query is parsed as T-SQL, restricted to one SELECT, checked against discovered tables and columns, rejected if it crosses databases or uses unapproved functions, and capped by rows, joins, AST size, and execution timeout. These controls supplement the required read-only SQL Server account; SQL parsing is not the only security boundary.

## Phase 2 API routes

- `GET/POST /api/databases`, `PUT/DELETE /api/databases/{id}`, `POST /api/databases/test`
- `GET /api/databases/{id}/access` and `PUT/DELETE /api/databases/{id}/access/{user_id}`
- `POST /api/schema/refresh`, `GET /api/schema/{database_id}`, and table/column description updates
- `GET/POST /api/company-mappings`, `PUT/DELETE /api/company-mappings/{id}`
- `GET/POST /api/business-dictionary`, `PUT/DELETE /api/business-dictionary/{id}`

NAV/Business Central captions are applied when the connected SQL database exposes compatible `Field` metadata with a caption column, and, when needed, matching `Object` metadata. Otherwise schema discovery still succeeds and captions remain empty. Table-prefix inference recognizes common NAV/BC tables; custom schemas can be maintained through the company mapping API.

## Phase 3 Text-to-SQL API

- `POST /api/chat/ask` detects intent, retrieves scoped schema and terminology, generates and validates SQL, executes it, and explains the query.
- `POST /api/sql/generate` returns validated SQL and its explanation without executing it.
- `POST /api/sql/validate` checks submitted T-SQL against the authorized database and discovered metadata.
- `POST /api/sql/execute` revalidates SQL and access before running the query.
- `POST /api/sql/explain` validates SQL and returns a structured explanation.

The `config/business_dictionary/nav_bc_examples.json` file includes illustrative examples such as ILE (Item Ledger Entry), VE (Value Entry), MTD/QTD/YTD, RM, STL, ATL, and Consumption. These examples are hints only. Company-specific dictionary entries take priority, and calculations that depend on an unconfigured rule (such as consumption, costing, units, or fiscal calendars) should ask for clarification.

The API sends the question, a bounded schema selection, and matching scoped terminology to OpenRouter. It never sends SQL Server usernames, passwords, encrypted credentials, or API keys. Configure each SQL Server login as read-only; the API does not accept model-generated commands and never delegates execution to the model.

## Phase 4 Dynamic Dashboards

- `POST /api/dashboards/generate` asks OpenRouter for a structured dashboard plan. The plan is validated against the allowed widget types, layout sizes, widget counts, and filter counts.
- Each planned widget question runs through the Phase 3 intent, schema, SQL generation, SQLGlot validation, grant/company recheck, and bounded SQL Server execution path. The model never supplies chart values or raw SQL in its dashboard plan.
- Dashboard filters and click-to-drill cross-filter options are resolved from actual widget result columns and values. Unmatched filter hints are omitted, and chart fields are matched only to returned columns.
- The React renderer uses reusable KPI, chart, and table components. Apache ECharts renders bar, line, area, pie, and donut charts with responsive grid spans.

## Phase 5 Conversations, insights, and comparisons

- `POST /api/conversations/ask` stores private conversation history with the selected database, company mapping, exact-match filters, bounded result samples, and validated SQL. Follow-up requests inherit the original database and company; the API rejects scope changes. Persisted filters are resolved against discovered columns, added as quoted SQL AST predicates, and validated again before execution.
- `GET /api/conversations`, `GET /api/conversations/{id}`, and `DELETE /api/conversations/{id}` operate on the signed-in user's conversations and recheck database access. Access is checked before and after query execution.
- `POST /api/insights/generate` runs a validated read-only query, then asks the configured reasoning model for observations grounded in exact rows and fields returned by SQL. The API rejects unsupported evidence references.
- `POST /api/comparisons/periods` runs the same validated query for two non-overlapping date ranges. The API resolves date columns from discovered schema, injects inclusive start/exclusive next-day bounds, and computes absolute and percentage changes.
- `POST /api/comparisons/companies` runs each company series within its own mapped schema scope, normalizes company-specific result fields, and reports values and changes against the first selected company. Company mappings can store a three-letter currency code. Cross-currency field conversion requires explicit target currency and exchange rates (target currency units per one source currency unit); the UI displays source currencies when values are not converted.
- The React Phase 5 screen provides conversation history and exact filters, business insight evidence, date range controls, and multi-company comparisons. Database grants and company scopes are rechecked for every request, including after model calls and query execution.

## Phase 6 Saved dashboards and exports

- Saved dashboard configurations and immutable version snapshots are stored in PostgreSQL. Snapshots contain the validated widget queries and presentation configuration, not cached result rows.
- `POST/GET /api/saved-dashboards`, `PUT/DELETE /api/saved-dashboards/{id}`, `PATCH /api/saved-dashboards/{id}/favorite`, version history and restore routes, plus fresh render and export routes support owner-scoped management.
- Opening a saved dashboard or exporting a report rechecks the current database grant, company mapping, and SQL policy, then reruns each widget query against the authorized SQL Server connection. Stale results are never used for reports.
- Filters are validated against options from the fresh query results and applied to widget data. Excel exports include an overview, filter selections, KPIs, native charts, and a detailed worksheet for every widget. PDF exports include filter context, KPI summaries, charts, and paginated detailed tables.
- Export values are escaped against spreadsheet formula injection. Excel and PDF dependencies are declared in the backend package.
- The Phase 6 UI supports favorites, fresh data, version history and restore, rebuilding a new version, and filter-aware Excel/PDF downloads.

## Checks

```powershell
cd backend
python -m pip install -e ".[dev]"
pytest
```

```powershell
cd frontend
npm install
npm run build
```

Backend tests use an in-memory SQLite application database, mocked OpenRouter responses, and mocked SQL Server metadata/execution. They do not need PostgreSQL, an ODBC driver, an ERP database, or OpenRouter credentials. Tests cover NAV joins and date calculations, SQL correction, invalid columns, unapproved tables, access revocation during conversations and saved dashboard exports, filter persistence and safe injection, evidence grounding, date-period comparisons, company field normalization, currency conversion, dashboard version persistence and restore, favorites, fresh filtered export rows, Excel chart/table content, PDF generation, and formula-injection protection. The Docker deployment installs Microsoft ODBC Driver 18, uses PostgreSQL for application data, and runs Alembic migrations before the API starts.

## Project map

```text
backend/     FastAPI app, SQLAlchemy models, Alembic migrations, tests
frontend/    React/Vite app, typed API client, auth state, workspace UI
config/      Model registry, NAV/BC terminology examples, and company-mapping extension point
database/    PostgreSQL migration documentation and seed extension point
deployment/  Nginx configuration for the containerized frontend
docs/        Architecture and phase boundaries
```

## Phase boundary

Phase 6 provides private conversational memory, follow-up questions with persistent database/company/filter context, evidence-based insights, date and company comparisons, PostgreSQL-backed saved dashboards with favorites and immutable versions, and filter-aware Excel/PDF reports. Dashboard and report values are derived from newly executed, authorized SQL results rather than saved or model-generated examples.
