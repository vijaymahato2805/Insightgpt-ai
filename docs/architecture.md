# InsightGPT AI architecture

The React client talks to the FastAPI service through a typed Axios client. The API owns authentication, authorization, configuration checks, and all provider secrets. SQLAlchemy sessions connect to PostgreSQL; Alembic owns schema changes. The model registry is version controlled while API keys and runtime model assignments are environment configuration.

Authentication uses a signed JWT in an HttpOnly cookie. Each access token carries the user's token version. Logout increments the stored version, which invalidates previously issued tokens. Role checks are performed in API dependencies.

The OpenRouter adapter is an isolated async HTTP client. It is not called by the browser and it does not execute SQL. Phase 3 orchestration retrieves bounded schema and scoped terminology, gets structured model outputs, and validates each query with SQLGlot before any execution. The executor rechecks the selected database grant and company scope, uses an allowlist of discovered tables and columns, enforces single-SELECT policy, row and AST/join caps, and applies a query timeout. Deployments must still use a read-only SQL Server account.

## Planned boundaries

- Phase 2 owns external SQL Server connections, schema metadata and company mappings.
- Phase 3 owns intent, schema selection, business terminology retrieval, SQL generation/correction/explanation, validation and controlled execution.
- Phase 4 asks the reasoning model for strict dashboard JSON containing only widget intent, visualization choices, layout hints, and field hints. Pydantic rejects invalid or excessive plans.
- Phase 4 runs every widget question through the existing Text-to-SQL generation and SQLGlot policy path, rechecks the database grant/company scope, and executes the validated query with the SQL Server row and timeout caps. No chart values come from the model.
- The API resolves chart fields and filter options against returned SQL columns and rows. The React/ECharts renderer implements query-backed KPIs, charts, tables, responsive layouts, and cross-filter drill-down.
- Phase 5 stores user-owned conversations with bounded query results, selected company mappings, and filters. Follow-ups keep their database scope, inject saved exact-match filters as SQL AST predicates, and recheck access around model and database work. Insights use evidence references validated against executed result rows; comparisons inject server-controlled period bounds and normalize NAV/BC fields and configured currency values.
- Phase 6 stores saved dashboard definitions and immutable versions in PostgreSQL. It excludes result samples from configuration snapshots. Detail, refresh, and export requests revalidate every stored widget query and execute it against the currently authorized database before rendering results.
- Excel and PDF report generation uses those fresh dashboard responses, including active filters, KPIs, charts, and detailed widget tables. Dashboard ownership, current database grants, and company scope are checked on list, favorite, version, restore, render, update, delete, and export routes.
