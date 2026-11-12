import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, Settings
from app.core.crypto import CredentialEncryptionError, CredentialVault
from app.llm.provider import OpenRouterProvider, ProviderConfigurationError, Task
from app.models.erp import (
    BusinessDictionaryEntry,
    CompanyMapping,
    DatabaseConnection,
    SchemaColumn,
    SchemaObject,
    SchemaRelationship,
)
from app.models.user import User
from app.services.database_access import get_connection_for_user
from app.sql.contracts import (
    BusinessTermContext,
    QueryIntent,
    SchemaSelection,
    SQLContextObject,
    SQLDraft,
    SQLExplanation,
    TextToSQLResult,
    TokenUsage,
)
from app.sql.validation import (
    AllowedTable,
    SQLPolicyError,
    SQLValidationResult,
    allowed_tables_from_schema,
    validate_read_query,
)

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
TOKEN_PATTERN = re.compile(r"[a-z0-9_$]+", re.IGNORECASE)
STOP_WORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "are",
    "by",
    "for",
    "from",
    "give",
    "in",
    "is",
    "me",
    "of",
    "on",
    "show",
    "that",
    "the",
    "to",
    "with",
    "what",
    "which",
    "who",
}


class LLMOutputError(RuntimeError):
    pass


@dataclass
class QueryContext:
    connection: DatabaseConnection
    company_mapping: CompanyMapping | None
    implicit_company_prefix: str | None
    schema_objects: list[SchemaObject]
    columns_by_object: dict[UUID, list[SchemaColumn]]
    relationships_by_object: dict[UUID, list[SchemaRelationship]]
    dictionary_entries: list[BusinessDictionaryEntry]
    allowed_tables: list[AllowedTable]

    @property
    def company_label(self) -> str:
        return (
            self.company_mapping.company_name
            if self.company_mapping
            else (self.implicit_company_prefix or self.connection.company_name or "not selected")
        )


@dataclass
class UsageAccumulator:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, result) -> None:
        self.prompt_tokens += result.prompt_tokens or 0
        self.completion_tokens += result.completion_tokens or 0
        self.total_tokens += result.total_tokens or 0

    def to_schema(self) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
        )


def load_query_context(
    db: Session,
    user: User,
    database_id: UUID,
    company_mapping_id: UUID | None,
) -> QueryContext:
    connection = get_connection_for_user(db, user, database_id)
    if not connection.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "This database connection is disabled")

    company_mapping = None
    if company_mapping_id:
        company_mapping = db.get(CompanyMapping, company_mapping_id)
        if company_mapping is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Company mapping not found")
        if company_mapping.database_connection_id != connection.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Company mapping does not belong to the selected database",
            )

    schema_objects = list(
        db.scalars(
            select(SchemaObject)
            .where(SchemaObject.database_connection_id == connection.id)
            .order_by(SchemaObject.schema_name, SchemaObject.object_name)
        )
    )
    if not schema_objects:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Refresh the database schema before asking analytics questions",
        )

    implicit_company_prefix = None
    if company_mapping is None and connection.erp_version in {
        "nav_2013_r2",
        "nav_2018",
        "business_central",
    }:
        mappings = list(
            db.scalars(
                select(CompanyMapping).where(CompanyMapping.database_connection_id == connection.id)
            )
        )
        if connection.company_name:
            company_mapping = next(
                (
                    item
                    for item in mappings
                    if item.company_name.casefold() == connection.company_name.casefold()
                ),
                None,
            )
        prefixes = {
            item.object_name.rsplit("$", 1)[0]
            for item in schema_objects
            if "$" in item.object_name and item.object_name.rsplit("$", 1)[0]
        }
        preferred_prefix = next(
            (
                prefix
                for prefix in prefixes
                if connection.company_name
                and prefix.casefold() == connection.company_name.casefold()
            ),
            None,
        )
        if company_mapping is None and len(prefixes) == 1:
            only_prefix = next(iter(prefixes))
            company_mapping = next(
                (
                    item
                    for item in mappings
                    if item.company_name.casefold() == only_prefix.casefold()
                ),
                None,
            )
        if company_mapping is None and len(mappings) == 1:
            company_mapping = mappings[0]
        if company_mapping is None:
            if preferred_prefix:
                implicit_company_prefix = preferred_prefix
            elif len(prefixes) == 1:
                implicit_company_prefix = next(iter(prefixes))
            elif len(prefixes) > 1:
                raise HTTPException(
                    422,
                    "Select a company mapping before querying this multi-company NAV/BC database",
                )
            elif len(mappings) > 1:
                raise HTTPException(
                    422,
                    "Select a company mapping before querying this NAV/BC database",
                )

    if company_mapping:
        allowed_names = {
            value.strip().strip("[]").casefold()
            for value in (company_mapping.table_mappings or {}).values()
        }
        company_prefix = f"{company_mapping.company_name.casefold()}$"
        schema_objects = [
            item
            for item in schema_objects
            if (
                item.object_name.casefold().startswith(company_prefix)
                or (
                    "$" not in item.object_name
                    and f"{item.schema_name}.{item.object_name}".casefold() in allowed_names
                )
            )
        ]
        if not schema_objects:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The selected company has no discovered or mapped schema objects",
            )
    elif implicit_company_prefix:
        schema_objects = [
            item
            for item in schema_objects
            if item.object_name.casefold().startswith(f"{implicit_company_prefix.casefold()}$")
        ]

    object_ids = [item.id for item in schema_objects]
    columns_by_object: dict[UUID, list[SchemaColumn]] = {item_id: [] for item_id in object_ids}
    for column in db.scalars(
        select(SchemaColumn)
        .where(SchemaColumn.schema_object_id.in_(object_ids))
        .order_by(SchemaColumn.schema_object_id, SchemaColumn.ordinal_position)
    ):
        columns_by_object[column.schema_object_id].append(column)
    relationships_by_object: dict[UUID, list[SchemaRelationship]] = {
        item_id: [] for item_id in object_ids
    }
    for relationship in db.scalars(
        select(SchemaRelationship)
        .where(SchemaRelationship.source_object_id.in_(object_ids))
        .order_by(SchemaRelationship.source_object_id, SchemaRelationship.source_column)
    ):
        relationships_by_object[relationship.source_object_id].append(relationship)

    dictionary_query = select(BusinessDictionaryEntry).where(
        BusinessDictionaryEntry.enabled.is_(True),
        or_(
            BusinessDictionaryEntry.database_connection_id.is_(None),
            BusinessDictionaryEntry.database_connection_id == connection.id,
        ),
    )
    if company_mapping:
        dictionary_query = dictionary_query.where(
            or_(
                BusinessDictionaryEntry.company_mapping_id.is_(None),
                BusinessDictionaryEntry.company_mapping_id == company_mapping.id,
            )
        )
    else:
        dictionary_query = dictionary_query.where(
            BusinessDictionaryEntry.company_mapping_id.is_(None)
        )
    dictionary_entries = list(db.scalars(dictionary_query.order_by(BusinessDictionaryEntry.term)))

    return QueryContext(
        connection=connection,
        company_mapping=company_mapping,
        implicit_company_prefix=implicit_company_prefix,
        schema_objects=schema_objects,
        columns_by_object=columns_by_object,
        relationships_by_object=relationships_by_object,
        dictionary_entries=dictionary_entries,
        allowed_tables=allowed_tables_from_schema(db, schema_objects, company_mapping),
    )


class TextToSQLService:
    """LLM orchestration with bounded schema retrieval and mandatory SQL policy validation."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = OpenRouterProvider(settings)
        self.system_prompt = _read_prompt("system_prompt.txt")
        self.last_usage = UsageAccumulator()

    async def generate(
        self,
        context: QueryContext,
        question: str,
    ) -> tuple[TextToSQLResult, SQLValidationResult, list[SchemaObject]]:
        usage = UsageAccumulator()
        terms = _retrieve_business_terms(context, question)
        intent = await self._structured_call(
            QueryIntent,
            "intent_detection.txt",
            {
                "QUESTION": json.dumps(question, ensure_ascii=False),
                "COMPANY": json.dumps(context.company_label, ensure_ascii=False),
                "TERMS": _json_dumps([item.model_dump() for item in terms]),
            },
            task="reasoning",
            usage=usage,
        )
        if intent.requested_company:
            requested = intent.requested_company.strip().casefold()
            selected_company = context.company_label.casefold()
            if not selected_company or requested != selected_company:
                intent.needs_clarification = True
                intent.clarification = (
                    "Select the authorized database and company mapping for "
                    f"{intent.requested_company}, then ask again."
                )
        if intent.needs_clarification:
            result = TextToSQLResult(
                database_id=context.connection.id,
                company_mapping_id=context.company_mapping.id if context.company_mapping else None,
                question=question,
                intent=intent,
                business_terms=[item.term for item in terms],
                needs_clarification=True,
                clarification=intent.clarification or "Please clarify the business rule to apply.",
                token_usage=usage.to_schema(),
            )
            return result, SQLValidationResult(sql="", tables=[], columns=[], max_rows=0), []

        candidates = _rank_schema(context, question, intent, terms)
        if not candidates:
            raise SQLPolicyError(["No relevant discovered schema objects matched the question"])
        try:
            selection = await self._structured_call(
                SchemaSelection,
                "schema_selection.txt",
                {
                    "QUESTION": json.dumps(question, ensure_ascii=False),
                    "INTENT": _json_dumps(intent.model_dump()),
                    "CANDIDATES": _json_dumps(
                        [_schema_payload(context, item) for item, _ in candidates]
                    ),
                },
                task="fast",
                usage=usage,
            )
            candidate_by_id = {item.id: item for item, _ in candidates}
            selected = [
                candidate_by_id[item_id]
                for item_id in selection.object_ids
                if item_id in candidate_by_id
            ]
            if not selected:
                selected = [item for item, _ in candidates[:8]]
        except LLMOutputError:
            selected = [item for item, _ in candidates[:8]]

        selected_payload = [_schema_payload(context, item) for item in selected]
        selected_keys = {
            (item.schema_name.casefold(), item.object_name.casefold()) for item in selected
        }
        selected_tables = [
            item
            for item in context.allowed_tables
            if (item.schema_name.casefold(), item.object_name.casefold()) in selected_keys
        ]
        correction_feedback: list[str] = []
        assumptions: list[str] = []
        draft = await self._structured_call(
            SQLDraft,
            "sql_generation.txt",
            {
                "QUESTION": json.dumps(question, ensure_ascii=False),
                "INTENT": _json_dumps(intent.model_dump()),
                "SCHEMA": _json_dumps(selected_payload),
                "TERMS": _json_dumps([item.model_dump() for item in terms]),
            },
            task="sql",
            usage=usage,
        )
        assumptions.extend(draft.assumptions)
        validation: SQLValidationResult | None = None
        for attempt in range(3):
            try:
                validation = validate_read_query(
                    draft.sql,
                    selected_tables,
                    max_rows=self.settings.sql_max_result_rows,
                    max_ast_nodes=self.settings.sql_max_ast_nodes,
                    max_joins=self.settings.sql_max_joins,
                )
                break
            except SQLPolicyError as exc:
                correction_feedback = exc.issues
                if attempt == 2:
                    raise
                draft = await self._structured_call(
                    SQLDraft,
                    "sql_correction.txt",
                    {
                        "QUESTION": json.dumps(question, ensure_ascii=False),
                        "INTENT": _json_dumps(intent.model_dump()),
                        "SCHEMA": _json_dumps(selected_payload),
                        "TERMS": _json_dumps([item.model_dump() for item in terms]),
                        "SQL": json.dumps(draft.sql, ensure_ascii=False),
                        "ERRORS": _json_dumps(correction_feedback),
                    },
                    task="sql",
                    usage=usage,
                )
                assumptions.extend(draft.assumptions)

        assert validation is not None
        explanation = await self.explain(
            context,
            validation.sql,
            question,
            terms=terms,
            used_objects=selected,
            usage=usage,
        )
        result = TextToSQLResult(
            database_id=context.connection.id,
            company_mapping_id=context.company_mapping.id if context.company_mapping else None,
            question=question,
            intent=intent,
            sql=validation.sql,
            explanation=explanation.explanation,
            explanation_notes=explanation.notes,
            selected_tables=[item.display_name for item in selected_tables],
            business_terms=[item.term for item in terms],
            assumptions=assumptions,
            token_usage=usage.to_schema(),
        )
        return result, validation, selected

    async def explain(
        self,
        context: QueryContext,
        sql: str,
        question: str | None,
        *,
        terms: list[BusinessTermContext] | None = None,
        used_objects: list[SchemaObject] | None = None,
        usage: UsageAccumulator | None = None,
    ) -> SQLExplanation:
        accumulator = usage or UsageAccumulator()
        active_terms = terms or _retrieve_business_terms(context, question or "")
        objects = used_objects or context.schema_objects
        result = await self._structured_call(
            SQLExplanation,
            "sql_explanation.txt",
            {
                "QUESTION": json.dumps(question or "Not supplied", ensure_ascii=False),
                "SQL": json.dumps(sql, ensure_ascii=False),
                "SCHEMA": _json_dumps([_schema_payload(context, item) for item in objects]),
                "TERMS": _json_dumps([item.model_dump() for item in active_terms]),
            },
            task="reasoning",
            usage=accumulator,
        )
        if usage is None:
            self.last_usage = accumulator
        return result

    async def _structured_call(
        self,
        model: type[T],
        prompt_name: str,
        values: dict[str, str],
        *,
        task: Task,
        usage: UsageAccumulator,
    ) -> T:
        prompt = _render_prompt(prompt_name, values)
        try:
            response = await self.provider.chat_completion(
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                task=task,
                temperature=0.0,
                max_tokens=1800,
            )
            usage.add(response)
            return _parse_structured(response.content, model)
        except ProviderConfigurationError as exc:
            logger.warning("Text-to-SQL model call failed for task %s", task)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "The configured language model is unavailable for this request",
            ) from exc
        except LLMOutputError:
            raise


def validate_for_user(
    db: Session,
    user: User,
    database_id: UUID,
    sql: str,
    company_mapping_id: UUID | None,
    settings: Settings,
) -> tuple[QueryContext, SQLValidationResult]:
    context = load_query_context(db, user, database_id, company_mapping_id)
    validation = validate_read_query(
        sql,
        context.allowed_tables,
        max_rows=settings.sql_max_result_rows,
        max_ast_nodes=settings.sql_max_ast_nodes,
        max_joins=settings.sql_max_joins,
    )
    return context, validation


def sqlserver_credentials(context: QueryContext, settings: Settings) -> dict[str, str] | None:
    connection = context.connection
    if connection.authentication_type == "windows":
        return None
    if not connection.credentials_encrypted:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Stored connection credentials are unavailable",
        )
    try:
        return CredentialVault(settings).decrypt(connection.credentials_encrypted)
    except CredentialEncryptionError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Stored credentials cannot be decrypted; check ENCRYPTION_KEY",
        ) from None


def execute_validated_sql(
    context: QueryContext,
    validation: SQLValidationResult,
    settings: Settings,
) -> tuple[list[str], list[dict[str, object]], bool]:
    from sqlalchemy.exc import SQLAlchemyError

    from app.database.sqlserver import create_sqlserver_engine
    from app.sqlserver_results import json_safe_value

    credentials = sqlserver_credentials(context, settings)
    engine = None
    try:
        engine = create_sqlserver_engine(_connection_target(context), credentials, settings)
        with engine.connect() as connection:
            # pyodbc applies Connection.timeout to every cursor on this connection.
            connection.connection.driver_connection.timeout = settings.sql_query_timeout_seconds
            result = connection.exec_driver_sql(validation.sql)
            columns = list(result.keys())
            fetched = result.fetchmany(settings.sql_max_result_rows + 1)
            truncated = len(fetched) > settings.sql_max_result_rows
            rows = [
                {name: json_safe_value(value) for name, value in zip(columns, row, strict=False)}
                for row in fetched[: settings.sql_max_result_rows]
            ]
            connection.rollback()
        return columns, rows, truncated
    except HTTPException:
        raise
    except (SQLAlchemyError, TimeoutError, OSError):
        logger.warning("Validated SQL execution failed for a configured connection")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "SQL Server could not complete the validated query; check the query and database availability",
        ) from None
    except Exception:  # noqa: BLE001 - ODBC driver errors are platform-specific.
        logger.warning("Validated SQL execution failed during driver setup")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "SQL Server could not complete the validated query; check the ODBC driver setup",
        ) from None
    finally:
        if engine is not None:
            engine.dispose()


def _connection_target(context: QueryContext):
    from app.database.sqlserver import SqlServerTarget

    return SqlServerTarget(
        context.connection.server,
        context.connection.database_name,
        context.connection.authentication_type,
    )


def _retrieve_business_terms(context: QueryContext, question: str) -> list[BusinessTermContext]:
    question_folded = question.casefold()
    query_tokens = _tokens(question)
    ranked: list[tuple[float, BusinessTermContext]] = []
    for entry in context.dictionary_entries:
        entry_tokens = _tokens(f"{entry.term} {entry.definition}")
        overlap = len(query_tokens & entry_tokens)
        score = float(overlap)
        if entry.term.casefold() in question_folded:
            score += 6.0
        if score > 0:
            source = (
                "company"
                if entry.company_mapping_id
                else ("database" if entry.database_connection_id else "global")
            )
            ranked.append(
                (
                    score + (2.0 if source == "company" else 1.0 if source == "database" else 0),
                    BusinessTermContext(
                        term=entry.term,
                        definition=entry.definition,
                        entry_type=entry.entry_type,
                        source=source,
                    ),
                )
            )
    ranked.sort(key=lambda item: (-item[0], item[1].term.casefold()))
    selected = [item for _, item in ranked[:12]]
    selected_keys = {item.term.casefold() for item in selected}

    for example in _example_terms():
        term = str(example.get("term", ""))
        if term and term.casefold() in question_folded and term.casefold() not in selected_keys:
            selected.append(
                BusinessTermContext(
                    term=term,
                    definition=str(example.get("definition", "")),
                    entry_type="example",
                    source="illustrative example; not an approved company rule",
                )
            )
    return selected[:16]


def _rank_schema(
    context: QueryContext,
    question: str,
    intent: QueryIntent,
    terms: list[BusinessTermContext],
) -> list[tuple[SchemaObject, float]]:
    query = " ".join(
        [question, *intent.metrics, *intent.dimensions, *intent.filters, intent.time_period or ""]
        + [f"{term.term} {term.definition}" for term in terms]
    )
    query_tokens = _tokens(query)
    scores: list[tuple[SchemaObject, float]] = []
    for item in context.schema_objects:
        columns = context.columns_by_object.get(item.id, [])
        table_tokens = _tokens(f"{item.object_name} {item.schema_name} {item.description or ''}")
        column_tokens = set()
        for column in columns:
            column_tokens.update(
                _tokens(f"{column.column_name} {column.caption or ''} {column.description or ''}")
            )
        table_match = len(query_tokens & table_tokens)
        column_match = len(query_tokens & column_tokens)
        exact_name = sum(
            3.0
            for term in [*intent.metrics, *intent.dimensions]
            if term and term.casefold() in item.object_name.casefold()
        )
        score = table_match * 2.0 + column_match + exact_name
        scores.append((item, score))
    scores.sort(
        key=lambda pair: (-pair[1], pair[0].schema_name.casefold(), pair[0].object_name.casefold())
    )

    selected = [(item, score) for item, score in scores if score > 0][:16]
    if not selected:
        selected = scores[: min(12, len(scores))]

    selected_ids = {item.id for item, _ in selected}
    selected_names = {item.object_name.casefold() for item, _ in selected}
    object_by_name = {item.object_name.casefold(): item for item in context.schema_objects}
    neighbors: list[tuple[SchemaObject, float]] = []
    for item, score in selected:
        for relationship in context.relationships_by_object.get(item.id, []):
            neighbor = object_by_name.get(relationship.target_table.casefold())
            if neighbor and neighbor.id not in selected_ids:
                neighbors.append((neighbor, score * 0.25))
        for source in context.schema_objects:
            if source.id in selected_ids:
                continue
            if any(
                relation.target_table.casefold() == item.object_name.casefold()
                for relation in context.relationships_by_object.get(source.id, [])
            ):
                neighbors.append((source, score * 0.25))
    for neighbor, score in neighbors:
        if neighbor.id not in selected_ids and len(selected) < 24:
            selected.append((neighbor, score))
            selected_ids.add(neighbor.id)
            selected_names.add(neighbor.object_name.casefold())
    return selected[:24]


def _schema_payload(context: QueryContext, item: SchemaObject) -> dict[str, object]:
    columns = context.columns_by_object.get(item.id, [])[:100]
    relationships = context.relationships_by_object.get(item.id, [])[:80]
    return SQLContextObject(
        id=item.id,
        schema_name=item.schema_name,
        object_name=item.object_name,
        object_type=item.object_type,
        description=item.description,
        columns=[
            {
                "name": column.column_name,
                "caption": column.caption,
                "description": column.description,
                "type": column.data_type,
                "primary_key": column.is_primary_key,
                "foreign_key": column.is_foreign_key,
            }
            for column in columns
        ],
        relationships=[
            {
                "source_column": item.source_column,
                "target_schema": item.target_schema,
                "target_table": item.target_table,
                "target_column": item.target_column,
            }
            for item in relationships
        ],
    ).model_dump(mode="json")


def _parse_structured[T: BaseModel](content: str, model: type[T]) -> T:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise LLMOutputError("The model returned no JSON object")
    try:
        payload = json.loads(cleaned[start : end + 1])
        return model.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise LLMOutputError("The model returned an invalid structured response") from exc


def _render_prompt(name: str, values: dict[str, str]) -> str:
    prompt = _read_prompt(name)
    for key, value in values.items():
        prompt = prompt.replace("{{" + key + "}}", value)
    return prompt


def _read_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_PATTERN.findall(value)
        if len(token) > 1 and token.casefold() not in STOP_WORDS
    }


@lru_cache(maxsize=1)
def _example_terms() -> list[dict[str, object]]:
    path = PROJECT_ROOT / "config" / "business_dictionary" / "nav_bc_examples.json"
    if not path.is_file():
        path = Path("/app/config/business_dictionary/nav_bc_examples.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("examples", []))
    except (OSError, ValueError, TypeError):
        logger.warning("Optional NAV/Business Central terminology examples are unavailable")
        return []
