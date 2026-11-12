import json
from uuid import UUID

from app.core.config import Settings
from app.schemas.analysis import (
    BusinessInsight,
    InsightEvidence,
    InsightPlan,
    InsightRequest,
    InsightResponse,
)
from app.services.text_to_sql import TextToSQLService, UsageAccumulator

PROMPT_NAME = "business_insights.txt"


class BusinessInsightService:
    def __init__(self, settings: Settings):
        self.sql_service = TextToSQLService(settings)

    async def analyze(
        self,
        *,
        database_id: UUID,
        company_mapping_id: UUID | None,
        company_name: str | None,
        request: InsightRequest,
        sql: str,
        columns: list[str],
        rows: list[dict[str, object]],
        row_count: int,
        truncated: bool,
    ) -> InsightResponse:
        if not rows:
            raise ValueError("No query rows are available to analyze")
        sample_rows = rows[:50]
        usage = UsageAccumulator()
        plan = await self.sql_service._structured_call(
            InsightPlan,
            PROMPT_NAME,
            {
                "MAX_INSIGHTS": str(request.max_insights),
                "QUESTION": json.dumps(request.question, ensure_ascii=False),
                "COMPANY": json.dumps(company_name or "Database default scope", ensure_ascii=False),
                "SQL": json.dumps(sql, ensure_ascii=False),
                "COLUMNS": json.dumps(columns[:80], ensure_ascii=False),
                "ROWS": json.dumps(sample_rows, ensure_ascii=False, separators=(",", ":")),
                "ROW_COUNT": str(row_count),
                "TRUNCATED": str(truncated).lower(),
            },
            task="reasoning",
            usage=usage,
        )
        if len(plan.insights) > request.max_insights:
            raise ValueError("The model returned more insights than requested")
        insights: list[BusinessInsight] = []
        for item in plan.insights:
            evidence: list[InsightEvidence] = []
            for ref in item.evidence:
                if ref.row_index >= len(sample_rows) or ref.field not in columns:
                    raise ValueError("The model referenced evidence outside the executed result")
                evidence.append(
                    InsightEvidence(field=ref.field, value=sample_rows[ref.row_index][ref.field])
                )
            insights.append(
                BusinessInsight(
                    title=item.title,
                    observation=item.observation,
                    direction=item.direction,
                    evidence=evidence,
                )
            )
        return InsightResponse(
            database_id=database_id,
            company_mapping_id=company_mapping_id,
            company_name=company_name,
            question=request.question,
            sql=sql,
            columns=columns,
            row_count=row_count,
            truncated=truncated,
            summary=plan.summary,
            insights=insights,
        )
