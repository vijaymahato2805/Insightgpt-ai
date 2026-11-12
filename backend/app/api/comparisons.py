from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.database.session import get_db
from app.models.erp import CompanyMapping
from app.models.user import User
from app.schemas.analysis import (
    CompanyComparisonRequest,
    CompanyComparisonResponse,
    CompanyComparisonRow,
    CompanyDelta,
    CompanyResult,
    PeriodComparisonRequest,
    PeriodComparisonResponse,
    PeriodComparisonRow,
)
from app.services.comparisons import (
    ComparisonInputError,
    aggregate_rows,
    apply_date_range,
    canonicalize_company_result,
    convert_currency,
    decimal_text,
    resolve_result_field,
)
from app.services.text_to_sql import (
    LLMOutputError,
    TextToSQLService,
    execute_validated_sql,
    load_query_context,
    validate_for_user,
)
from app.sql.validation import SQLPolicyError

router = APIRouter(prefix="/comparisons", tags=["comparisons"])


@router.post("/periods", response_model=PeriodComparisonResponse)
async def compare_periods(
    payload: PeriodComparisonRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PeriodComparisonResponse:
    context = load_query_context(db, user, payload.database_id, payload.company_mapping_id)
    mapping_id = context.company_mapping.id if context.company_mapping else None
    query_request = _comparison_question(
        payload.question,
        payload.metric_field,
        payload.dimension_fields,
        date_field=payload.date_field,
        company_mapping=context.company_mapping,
    )
    generated, _ = await _generate(context, query_request, settings)
    assert generated.sql

    try:
        current_sql = apply_date_range(
            context,
            generated.sql,
            payload.date_field,
            payload.current_start,
            payload.current_end,
        )
        comparison_sql = apply_date_range(
            context,
            generated.sql,
            payload.date_field,
            payload.comparison_start,
            payload.comparison_end,
        )
        current_context, current_validation = validate_for_user(
            db, user, payload.database_id, current_sql, mapping_id, settings
        )
        previous_context, previous_validation = validate_for_user(
            db, user, payload.database_id, comparison_sql, mapping_id, settings
        )
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    except ComparisonInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

    current_columns, current_rows, _ = await run_in_threadpool(
        execute_validated_sql, current_context, current_validation, settings
    )
    previous_columns, previous_rows, _ = await run_in_threadpool(
        execute_validated_sql, previous_context, previous_validation, settings
    )
    mapping = context.company_mapping
    current_columns, current_rows = canonicalize_company_result(
        mapping, current_columns, current_rows
    )
    previous_columns, previous_rows = canonicalize_company_result(
        mapping, previous_columns, previous_rows
    )
    if current_columns != previous_columns:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The database returned inconsistent result columns between comparison periods",
        )

    try:
        metric_field = resolve_result_field(current_columns, payload.metric_field)
        dimension_fields = [
            resolve_result_field(current_columns, field) for field in payload.dimension_fields
        ]
        current = aggregate_rows(current_rows, metric_field, dimension_fields)
        previous = aggregate_rows(previous_rows, metric_field, dimension_fields)
    except ComparisonInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

    output_rows = []
    for key in sorted(set(current) | set(previous), key=repr):
        current_value = current.get(key)
        previous_value = previous.get(key)
        change = current_value - previous_value if current_value is not None and previous_value is not None else None
        percentage = (
            change / abs(previous_value) * Decimal(100)
            if change is not None and previous_value not in {None, Decimal(0)}
            else None
        )
        output_rows.append(
            PeriodComparisonRow(
                dimensions=dict(zip(dimension_fields, key, strict=True)),
                current_value=decimal_text(current_value) if current_value is not None else None,
                comparison_value=decimal_text(previous_value) if previous_value is not None else None,
                absolute_change=decimal_text(change) if change is not None else None,
                percentage_change=decimal_text(percentage) if percentage is not None else None,
            )
        )

    # Recheck access after both period queries have completed.
    load_query_context(db, user, payload.database_id, mapping_id)
    return PeriodComparisonResponse(
        database_id=payload.database_id,
        company_mapping_id=mapping_id,
        currency_code=mapping.currency_code if mapping else None,
        question=payload.question,
        date_field=payload.date_field,
        metric_field=metric_field,
        dimension_fields=dimension_fields,
        current_start=payload.current_start,
        current_end=payload.current_end,
        comparison_start=payload.comparison_start,
        comparison_end=payload.comparison_end,
        rows=output_rows,
    )


@router.post("/companies", response_model=CompanyComparisonResponse)
async def compare_companies(
    payload: CompanyComparisonRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CompanyComparisonResponse:
    contexts = []
    for mapping_id in payload.company_mapping_ids:
        context = load_query_context(db, user, payload.database_id, mapping_id)
        if context.company_mapping is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Select an explicit company mapping for every comparison series",
            )
        contexts.append((context.company_mapping, context))

    currency_codes = [
        mapping.currency_code.upper() if mapping.currency_code else None
        for mapping, _ in contexts
    ]
    target_currency = _target_currency(payload, currency_codes) if payload.currency_fields else None
    if payload.target_currency_code and not payload.currency_fields:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Select at least one currency field when requesting currency conversion",
        )
    if payload.currency_fields and any(code is None for code in currency_codes):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Set currency codes on every selected company mapping before converting currency fields",
        )
    if payload.currency_fields and target_currency is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Set a target currency when the selected companies use different currencies",
        )

    generated_results: list[CompanyResult] = []
    aggregates: list[dict[tuple[object, ...], Decimal]] = []
    canonical_metric = payload.metric_field
    canonical_dimensions = payload.dimension_fields
    service = TextToSQLService(settings)
    for (mapping, context), source_currency in zip(contexts, currency_codes, strict=True):
        question = _comparison_question(
            payload.question,
            payload.metric_field,
            payload.dimension_fields,
            company_mapping=mapping,
        )
        generated, _ = await _generate_with_service(context, question, service)
        assert generated.sql
        try:
            latest_context, validation = validate_for_user(
                db,
                user,
                payload.database_id,
                generated.sql,
                mapping.id,
                settings,
            )
        except SQLPolicyError as exc:
            raise _policy_error(exc) from None
        columns, rows, truncated = await run_in_threadpool(
            execute_validated_sql, latest_context, validation, settings
        )
        try:
            columns, rows = canonicalize_company_result(mapping, columns, rows)
            metric_field = resolve_result_field(columns, payload.metric_field)
            dimension_fields = [
                resolve_result_field(columns, field) for field in payload.dimension_fields
            ]
            currency_fields = [
                resolve_result_field(columns, field) for field in payload.currency_fields
            ]
            if target_currency:
                assert source_currency is not None
                rows = convert_currency(
                    rows,
                    currency_fields,
                    source_currency,
                    target_currency,
                    payload.exchange_rates,
                )
            aggregates.append(aggregate_rows(rows, metric_field, dimension_fields))
        except ComparisonInputError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

        canonical_metric = metric_field
        canonical_dimensions = dimension_fields
        generated_results.append(
            CompanyResult(
                company_mapping_id=mapping.id,
                company_name=mapping.company_name,
                source_currency_code=source_currency,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
            )
        )

    # A grant or company mapping can change while model calls and queries are in flight.
    for mapping, _ in contexts:
        load_query_context(db, user, payload.database_id, mapping.id)

    company_names = [mapping.company_name for mapping, _ in contexts]
    group_keys = set().union(*(values.keys() for values in aggregates))
    comparison_rows: list[CompanyComparisonRow] = []
    for key in sorted(group_keys, key=repr):
        values = [aggregate.get(key) for aggregate in aggregates]
        baseline = values[0]
        values_by_company = {
            name: decimal_text(value) if value is not None else None
            for name, value in zip(company_names, values, strict=True)
        }
        changes: dict[str, CompanyDelta] = {}
        if baseline is not None:
            for name, value in zip(company_names[1:], values[1:], strict=True):
                if value is None:
                    continue
                difference = value - baseline
                percentage = (
                    difference / abs(baseline) * Decimal(100)
                    if baseline != 0
                    else None
                )
                changes[name] = CompanyDelta(
                    absolute_change=decimal_text(difference),
                    percentage_change=decimal_text(percentage) if percentage is not None else None,
                )
        comparison_rows.append(
            CompanyComparisonRow(
                dimensions=dict(zip(canonical_dimensions, key, strict=True)),
                values_by_company=values_by_company,
                changes_vs_baseline=changes,
            )
        )

    return CompanyComparisonResponse(
        database_id=payload.database_id,
        question=payload.question,
        metric_field=canonical_metric,
        dimension_fields=canonical_dimensions,
        baseline_company=company_names[0],
        target_currency_code=target_currency,
        currency_fields=payload.currency_fields,
        companies=generated_results,
        rows=comparison_rows,
    )


async def _generate(context, question: str, settings: Settings):
    return await _generate_with_service(context, question, TextToSQLService(settings))


async def _generate_with_service(context, question: str, service: TextToSQLService):
    try:
        result, _, _ = await service.generate(context, question)
    except SQLPolicyError as exc:
        raise _policy_error(exc) from None
    except LLMOutputError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The language model could not prepare a safe comparison query",
        ) from None
    if result.needs_clarification or not result.sql:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            result.clarification or "Please clarify the comparison question",
        )
    return result, service


def _comparison_question(
    question: str,
    metric_field: str,
    dimension_fields: list[str],
    *,
    date_field: str | None = None,
    company_mapping: CompanyMapping | None = None,
) -> str:
    dimensions = ", ".join(dimension_fields) if dimension_fields else "no dimensions"
    date_note = (
        f" Reference the discovered date field {date_field!r} in the query source; "
        "do not add period bounds because the application adds the exact requested ranges."
        if date_field
        else ""
    )
    mapped_fields: list[str] = []
    if company_mapping is not None:
        for canonical in [metric_field, *dimension_fields, *([date_field] if date_field else [])]:
            matches = {
                actual
                for entity_fields in (company_mapping.field_mappings or {}).values()
                for field, actual in entity_fields.items()
                if _field_key(field) == _field_key(canonical)
            }
            if len(matches) == 1:
                actual = next(iter(matches))
                mapped_fields.append(
                    f"canonical field {canonical!r} maps to physical column [{actual}]"
                )
    mapping_note = (
        " Company metadata: " + "; ".join(mapped_fields)
        + ". Use these physical columns and alias each projection back to its canonical field name."
        if mapped_fields
        else ""
    )
    return (
        f"{question}. Return metric field {metric_field!r} aggregated by {dimensions}."
        f"{date_note}{mapping_note}"
    )


def _field_key(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _target_currency(
    payload: CompanyComparisonRequest, currency_codes: list[str | None]
) -> str | None:
    unique = set(currency_codes)
    known = {item for item in unique if item is not None}
    if payload.target_currency_code:
        return payload.target_currency_code
    if len(known) == 1 and None not in unique:
        return next(iter(known))
    return None


def _policy_error(exc: SQLPolicyError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": "SQL failed the read-only policy checks", "issues": exc.issues},
    )
