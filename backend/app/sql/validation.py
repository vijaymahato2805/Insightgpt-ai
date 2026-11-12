from dataclasses import dataclass
from uuid import UUID

import sqlglot
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlglot import ErrorLevel, exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.models.erp import CompanyMapping, SchemaColumn, SchemaObject
from app.sql.contracts import SQLValidationResult

SAFE_FUNCTION_NODES = {
    "Abs",
    "And",
    "Avg",
    "Ceil",
    "Cast",
    "Coalesce",
    "Count",
    "Convert",
    "CurrentDate",
    "CurrentTimestamp",
    "DateAdd",
    "DateDiff",
    "DateFromParts",
    "DatePart",
    "DateStrToDate",
    "DenseRank",
    "Extract",
    "Floor",
    "FirstValue",
    "Greatest",
    "If",
    "IsNull",
    "LastDay",
    "LastValue",
    "Lag",
    "Lead",
    "Least",
    "Length",
    "Lower",
    "LTrim",
    "Max",
    "Min",
    "Month",
    "Nullif",
    "Ntile",
    "Or",
    "Rank",
    "Replace",
    "Power",
    "Round",
    "RowNumber",
    "RTrim",
    "Substring",
    "Sum",
    "TimeStrToTime",
    "Trim",
    "TryCast",
    "Upper",
    "Year",
}


@dataclass(frozen=True)
class AllowedTable:
    schema_name: str
    object_name: str
    columns: frozenset[str]

    @property
    def display_name(self) -> str:
        return f"{self.schema_name}.{self.object_name}"


class SQLPolicyError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def allowed_tables_from_schema(
    db: Session,
    objects: list[SchemaObject],
    company_mapping: CompanyMapping | None = None,
) -> list[AllowedTable]:
    mapped_names: set[str] = set()
    company_name = ""
    if company_mapping is not None:
        company_name = str(getattr(company_mapping, "company_name", "")).casefold()
        raw_mappings = getattr(company_mapping, "table_mappings", {}) or {}
        for actual_name in raw_mappings.values():
            mapped_names.add(str(actual_name).strip().strip("[]").casefold())

    object_ids = [item.id for item in objects]
    columns_by_object: dict[UUID, set[str]] = {object_id: set() for object_id in object_ids}
    if object_ids:
        for column in db.scalars(
            select(SchemaColumn).where(SchemaColumn.schema_object_id.in_(object_ids))
        ):
            columns_by_object[column.schema_object_id].add(column.column_name.casefold())

    tables: list[AllowedTable] = []
    for item in objects:
        if item.object_type != "table" and item.object_type != "view":
            continue
        full_name = f"{item.schema_name}.{item.object_name}".casefold()
        company_prefixed = bool(company_name) and item.object_name.casefold().startswith(
            f"{company_name}$"
        )
        if company_mapping is not None:
            if "$" in item.object_name and not company_prefixed:
                continue
            if not company_prefixed and full_name not in mapped_names:
                continue
        tables.append(
            AllowedTable(
                schema_name=item.schema_name,
                object_name=item.object_name,
                columns=frozenset(columns_by_object[item.id]),
            )
        )
    return tables


def validate_read_query(
    sql: str,
    tables: list[AllowedTable],
    *,
    max_rows: int,
    max_ast_nodes: int = 1200,
    max_joins: int = 8,
) -> SQLValidationResult:
    if not sql.strip():
        raise SQLPolicyError(["SQL query is required"])
    if len(sql) > 20000:
        raise SQLPolicyError(["SQL query exceeds the allowed size"])
    if max_rows < 1:
        raise SQLPolicyError(["The row limit must be positive"])

    try:
        statements = sqlglot.parse(sql, read="tsql", error_level=ErrorLevel.RAISE)
    except sqlglot.errors.ParseError:
        raise SQLPolicyError(["SQL could not be parsed as a SQL Server query"]) from None
    if len(statements) != 1 or statements[0] is None:
        raise SQLPolicyError(["Only one SQL statement is permitted"])

    query = statements[0]
    if not isinstance(query, exp.Query):
        raise SQLPolicyError(["Only read-only SELECT queries are permitted"])
    if sum(1 for _ in query.walk()) > max_ast_nodes:
        raise SQLPolicyError(["SQL query exceeds the configured complexity limit"])
    if sum(1 for _ in query.find_all(exp.Join)) > max_joins:
        raise SQLPolicyError(["SQL query exceeds the configured join limit"])
    issues = _unsafe_expression_issues(query)
    if issues:
        raise SQLPolicyError(issues)

    table_lookup = {
        (table.schema_name.casefold(), table.object_name.casefold()): table for table in tables
    }
    by_name: dict[str, list[AllowedTable]] = {}
    for table in tables:
        by_name.setdefault(table.object_name.casefold(), []).append(table)

    source_tables: dict[int, AllowedTable] = {}
    referenced_tables: set[str] = set()
    for scope in traverse_scope(query):
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                if not isinstance(source.this, exp.Identifier):
                    raise SQLPolicyError(["Table-valued functions are not permitted"])
                if source.catalog:
                    raise SQLPolicyError(["Cross-database table references are not permitted"])
                schema_name = source.db or ""
                object_name = source.name
                if schema_name:
                    allowed = table_lookup.get((schema_name.casefold(), object_name.casefold()))
                else:
                    matches = by_name.get(object_name.casefold(), [])
                    allowed = matches[0] if len(matches) == 1 else None
                    if len(matches) > 1:
                        raise SQLPolicyError(
                            [f"Table {object_name!r} is ambiguous; qualify it with its schema"]
                        )
                if allowed is None:
                    raise SQLPolicyError(
                        [f"Table {object_name!r} is not available in this database scope"]
                    )
                source_tables[id(source)] = allowed
                referenced_tables.add(allowed.display_name)
            elif isinstance(source, Scope):
                continue

    referenced_columns: set[str] = set()
    for scope in traverse_scope(query):
        sources_by_alias = {key.casefold(): value for key, value in scope.sources.items()}
        output_aliases = _explicit_projection_aliases(scope.expression)
        for column in scope.columns:
            column_name = column.name
            if column_name == "*":
                if column.table and column.table.casefold() not in sources_by_alias:
                    raise SQLPolicyError([f"Unknown table qualifier {column.table!r}"])
                continue
            if column.catalog:
                raise SQLPolicyError(["Cross-database column references are not permitted"])
            qualifier = column.table.casefold() if column.table else ""
            if qualifier:
                source = sources_by_alias.get(qualifier)
                if source is None:
                    raise SQLPolicyError([f"Unknown table qualifier {column.table!r}"])
                if isinstance(source, exp.Table):
                    allowed = source_tables.get(id(source))
                    if allowed is None or column_name.casefold() not in allowed.columns:
                        raise SQLPolicyError(
                            [f"Column {column_name!r} is not present on table {column.table!r}"]
                        )
                    if column.db and column.db.casefold() != allowed.schema_name.casefold():
                        raise SQLPolicyError(["Column schema does not match its table"])
                    referenced_columns.add(f"{allowed.display_name}.{column_name}")
                elif isinstance(source, Scope):
                    output_names = _scope_output_names(source)
                    if column_name.casefold() not in output_names:
                        raise SQLPolicyError(
                            [
                                f"Column {column_name!r} is not projected by derived table {column.table!r}"
                            ]
                        )
                continue

            matches = _matching_sources(scope, column_name, source_tables)
            derived_matches = sum(
                1
                for source in scope.sources.values()
                if isinstance(source, Scope)
                and column_name.casefold() in _scope_output_names(source)
            )
            if len(matches) + derived_matches > 1:
                raise SQLPolicyError(
                    [f"Column {column_name!r} is ambiguous; qualify it with a table alias"]
                )
            if len(matches) == 1:
                allowed = matches[0]
                referenced_columns.add(f"{allowed.display_name}.{column_name}")
            elif derived_matches == 0 and not _is_order_by_alias(
                column, scope.expression, output_aliases
            ):
                raise SQLPolicyError(
                    [f"Column {column_name!r} was not found in the selected schema"]
                )

    if not referenced_tables:
        raise SQLPolicyError(["Query must read from an authorized discovered table or view"])

    limit = query.args.get("limit")
    if limit is not None:
        if limit.args.get("percent"):
            raise SQLPolicyError(["TOP PERCENT is not supported by the row limit policy"])
        limit_value = limit.args.get("expression")
        if not isinstance(limit_value, exp.Literal) or not limit_value.is_int:
            raise SQLPolicyError(["A row limit must use a constant integer"])
        requested_limit = int(limit_value.this)
        if requested_limit < 1:
            raise SQLPolicyError(["The row limit must be positive"])
        if requested_limit > max_rows:
            limit.set("expression", exp.Literal.number(max_rows))
    else:
        query.limit(max_rows, copy=False)

    return SQLValidationResult(
        sql=query.sql(dialect="tsql", comments=False),
        tables=sorted(referenced_tables),
        columns=sorted(referenced_columns),
        max_rows=max_rows,
    )


def _unsafe_expression_issues(query: exp.Expression) -> list[str]:
    if query.args.get("hint") or query.args.get("options"):
        return ["SQL Server query hints and options are not permitted"]
    forbidden_names = {
        "Alter",
        "Command",
        "Create",
        "Delete",
        "Drop",
        "Execute",
        "Insert",
        "Into",
        "Lock",
        "Merge",
        "NextValueFor",
        "Parameter",
        "Set",
        "Transaction",
        "TruncateTable",
        "Update",
    }
    for node in query.walk():
        if type(node).__name__ in forbidden_names:
            return ["SQL contains a write, DDL, execution, or locking operation"]
        if isinstance(node, exp.Func) and type(node).__name__ not in SAFE_FUNCTION_NODES:
            return [f"Function {node.sql_name()} is not approved for read-only queries"]
        if isinstance(node, exp.Table) and node.args.get("hints"):
            return ["SQL Server table hints are not permitted"]
    return []


def _matching_sources(
    scope: Scope,
    column_name: str,
    source_tables: dict[int, AllowedTable],
) -> list[AllowedTable]:
    matches: list[AllowedTable] = []
    for source in scope.sources.values():
        if isinstance(source, exp.Table):
            allowed = source_tables.get(id(source))
            if allowed and column_name.casefold() in allowed.columns:
                matches.append(allowed)
        elif isinstance(source, Scope) and column_name.casefold() in _scope_output_names(source):
            continue
    return matches


def _projection_names(expression: exp.Expression) -> set[str]:
    if not isinstance(expression, exp.Select):
        return set()
    return {item.alias_or_name.casefold() for item in expression.expressions if item.alias_or_name}


def _explicit_projection_aliases(expression: exp.Expression) -> set[str]:
    if not isinstance(expression, exp.Select):
        return set()
    return {
        projection.alias.casefold()
        for projection in expression.expressions
        if isinstance(projection, exp.Alias) and projection.alias
    }


def _is_order_by_alias(
    column: exp.Column,
    expression: exp.Expression,
    output_aliases: set[str],
) -> bool:
    return bool(
        column.name.casefold() in output_aliases
        and column.find_ancestor(exp.Order) is not None
        and isinstance(expression, exp.Select)
    )


def _scope_output_names(scope: Scope) -> set[str]:
    names = _projection_names(scope.expression)
    if "*" in names:
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                # Wildcard output validation is left to the inner scope's physical columns.
                continue
    return names
