from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlglot
from sqlglot import exp

from app.services.text_to_sql import QueryContext


class ComparisonInputError(ValueError):
    pass


def apply_date_range(
    context: QueryContext,
    sql: str,
    date_field: str,
    start: date,
    end: date,
) -> str:
    """Inject inclusive, schema-validated date bounds into a generated SELECT."""
    query = sqlglot.parse_one(sql, read="tsql")
    if not isinstance(query, exp.Select):
        raise ComparisonInputError("A period comparison requires a SELECT query")
    column = resolve_date_column(context, query, date_field)
    condition = exp.and_(
        exp.GTE(this=column.copy(), expression=exp.Literal.string(start.isoformat())),
        exp.LT(
            this=column.copy(),
            expression=exp.Literal.string((end + timedelta(days=1)).isoformat()),
        ),
    )
    where = query.args.get("where")
    if where is None:
        query.set("where", exp.Where(this=condition))
    else:
        query.set("where", exp.Where(this=exp.and_(where.this.copy(), condition)))
    return query.sql(dialect="tsql")


def resolve_date_column(context: QueryContext, query: exp.Query, field_hint: str) -> exp.Column:
    table_by_key = {
        (item.schema_name.casefold(), item.object_name.casefold()): item
        for item in context.schema_objects
    }
    requested_table, requested_field = _split_field_hint(field_hint)
    candidates: dict[tuple[str, str], exp.Column] = {}
    for source in query.find_all(exp.Table):
        if source.find_ancestor(exp.Select) is not query:
            continue
        schema_name = source.db or "dbo"
        table_name = source.name
        schema_object = table_by_key.get((schema_name.casefold(), table_name.casefold()))
        if schema_object is None:
            schema_object = next(
                (
                    item
                    for item in context.schema_objects
                    if item.object_name.casefold() == table_name.casefold()
                    and (not source.db or item.schema_name.casefold() == source.db.casefold())
                ),
                None,
            )
        if schema_object is None:
            continue
        if requested_table and not _table_hint_matches(
            requested_table, schema_object.object_name, source.alias_or_name
        ):
            continue
        entity = schema_object.object_name.split("$", 1)[-1]
        mapped_names = _mapped_actual_fields(context, entity, requested_field)
        for schema_column in context.columns_by_object.get(schema_object.id, []):
            data_type = schema_column.data_type.casefold()
            if "date" not in data_type:
                continue
            matches = {
                _normalize(schema_column.column_name),
                _normalize(schema_column.caption or ""),
                *(_normalize(item) for item in mapped_names),
            }
            if _normalize(requested_field) not in matches:
                continue
            alias = source.alias_or_name
            key = (alias.casefold(), schema_column.column_name.casefold())
            candidates[key] = exp.Column(
                this=exp.to_identifier(schema_column.column_name),
                table=exp.to_identifier(alias),
            )
    if len(candidates) != 1:
        raise ComparisonInputError(
            "The date field must identify one discovered date column in the query tables"
        )
    return next(iter(candidates.values()))


def apply_conversation_filters(
    context: QueryContext, sql: str, filters: list[dict[str, str]]
) -> str:
    """Apply persisted exact-match filters using discovered columns and SQL AST literals."""
    if not filters:
        return sql
    query = sqlglot.parse_one(sql, read="tsql")
    if not isinstance(query, exp.Select):
        raise ComparisonInputError("Conversation filters require a SELECT query")
    conditions: list[exp.Expression] = []
    for item in filters:
        field_hint = item["field"]
        column = resolve_schema_column(context, query, field_hint)
        conditions.append(
            exp.EQ(this=column, expression=exp.Literal.string(item["value"]))
        )
    condition = conditions[0]
    for additional in conditions[1:]:
        condition = exp.and_(condition, additional)
    where = query.args.get("where")
    if where is None:
        query.set("where", exp.Where(this=condition))
    else:
        query.set("where", exp.Where(this=exp.and_(where.this.copy(), condition)))
    return query.sql(dialect="tsql")


def resolve_schema_column(
    context: QueryContext, query: exp.Query, field_hint: str
) -> exp.Column:
    table_by_key = {
        (item.schema_name.casefold(), item.object_name.casefold()): item
        for item in context.schema_objects
    }
    requested_table, requested_field = _split_field_hint(field_hint)
    candidates: dict[tuple[str, str], exp.Column] = {}
    for source in query.find_all(exp.Table):
        if source.find_ancestor(exp.Select) is not query:
            continue
        schema_name = source.db or "dbo"
        schema_object = table_by_key.get((schema_name.casefold(), source.name.casefold()))
        if schema_object is None:
            schema_object = next(
                (
                    item
                    for item in context.schema_objects
                    if item.object_name.casefold() == source.name.casefold()
                    and (not source.db or item.schema_name.casefold() == source.db.casefold())
                ),
                None,
            )
        if schema_object is None:
            continue
        alias = source.alias_or_name
        if requested_table and not _table_hint_matches(
            requested_table, schema_object.object_name, alias
        ):
            continue
        entity = schema_object.object_name.split("$", 1)[-1]
        mapped_names = _mapped_actual_fields(context, entity, requested_field)
        for schema_column in context.columns_by_object.get(schema_object.id, []):
            names = {
                _normalize(schema_column.column_name),
                _normalize(schema_column.caption or ""),
                *(_normalize(item) for item in mapped_names),
            }
            if _normalize(requested_field) not in names:
                continue
            key = (alias.casefold(), schema_column.column_name.casefold())
            candidates[key] = exp.Column(
                this=exp.to_identifier(schema_column.column_name),
                table=exp.to_identifier(alias),
            )
    if len(candidates) != 1:
        raise ComparisonInputError(
            f"Filter field {field_hint!r} must identify one discovered query column"
        )
    return next(iter(candidates.values()))


def canonicalize_company_result(
    company_mapping,
    columns: list[str],
    rows: list[dict[str, object]],
) -> tuple[list[str], list[dict[str, object]]]:
    if company_mapping is None:
        return columns, rows
    rename: dict[str, str] = {}
    for column in columns:
        matches: set[str] = set()
        for entity_fields in (company_mapping.field_mappings or {}).values():
            for canonical, actual in entity_fields.items():
                if _normalize(column) in {_normalize(canonical), _normalize(actual)}:
                    matches.add(canonical)
        if len(matches) > 1:
            raise ComparisonInputError(
                f"Company field mapping is ambiguous for result column {column!r}"
            )
        rename[column] = next(iter(matches)) if matches else column
    normalized_names = [rename[column] for column in columns]
    if len({_normalize(name) for name in normalized_names}) != len(normalized_names):
        raise ComparisonInputError("Company field mappings create duplicate canonical result fields")
    normalized_rows = [
        {rename[column]: row.get(column) for column in columns}
        for row in rows
    ]
    return normalized_names, normalized_rows


def resolve_result_field(columns: list[str], field_hint: str) -> str:
    target = _normalize(field_hint)
    exact = [column for column in columns if _normalize(column) == target]
    if len(exact) == 1:
        return exact[0]
    partial = [
        column
        for column in columns
        if target and (target in _normalize(column) or _normalize(column) in target)
    ]
    if len(partial) == 1:
        return partial[0]
    raise ComparisonInputError(f"Result field {field_hint!r} was not found unambiguously")


def aggregate_rows(
    rows: list[dict[str, object]], metric_field: str, dimension_fields: list[str]
) -> dict[tuple[object, ...], Decimal]:
    values: dict[tuple[object, ...], Decimal] = {}
    for row in rows:
        metric = _decimal(row.get(metric_field))
        key = tuple(row.get(field) for field in dimension_fields)
        values[key] = values.get(key, Decimal(0)) + metric
    return values


def decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _decimal(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ComparisonInputError("The selected metric has a null or non-numeric result")
    try:
        result = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ComparisonInputError("The selected metric is not numeric") from None
    if not result.is_finite():
        raise ComparisonInputError("The selected metric is not finite")
    return result


def convert_currency(
    rows: list[dict[str, object]],
    currency_fields: list[str],
    source_currency: str,
    target_currency: str,
    exchange_rates: dict[str, Decimal],
) -> list[dict[str, object]]:
    if source_currency == target_currency:
        rate = Decimal(1)
    else:
        rate = exchange_rates.get(source_currency)
        if rate is None or rate <= 0:
            raise ComparisonInputError(
                f"An exchange rate from {source_currency} to {target_currency} is required"
            )
    converted = [dict(row) for row in rows]
    for row in converted:
        for field in currency_fields:
            if row.get(field) is None:
                continue
            row[field] = decimal_text(_decimal(row[field]) * rate)
    return converted


def _mapped_actual_fields(context: QueryContext, entity: str, canonical_field: str) -> set[str]:
    result: set[str] = set()
    mapping = context.company_mapping
    if mapping is None:
        return result
    for entity_key, fields in (mapping.field_mappings or {}).items():
        if _normalize(entity_key) not in {_normalize(entity), _normalize("$" + entity)}:
            continue
        for canonical, actual in fields.items():
            if _normalize(canonical) == _normalize(canonical_field):
                result.add(actual)
    return result


def _split_field_hint(value: str) -> tuple[str | None, str]:
    if "." not in value:
        return None, value.strip()
    table, field = value.rsplit(".", 1)
    return table.strip(), field.strip()


def _table_hint_matches(hint: str, object_name: str, alias: str) -> bool:
    normalized = _normalize(hint)
    return normalized in {_normalize(object_name), _normalize(alias), _normalize(object_name.split("$", 1)[-1])}


def _normalize(value: str) -> str:
    return "".join(char.casefold() for char in value if char.isalnum())
