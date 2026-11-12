import json

MAX_CONTEXT_MESSAGES = 12
MAX_CONTEXT_ROWS = 20


def contextualize_question(question: str, active_filters: list[dict[str, str]], messages) -> str:
    context_messages = []
    for message in messages[-MAX_CONTEXT_MESSAGES:]:
        item: dict[str, object] = {"role": message.role, "content": message.content[:1500]}
        if message.role == "assistant" and message.result_columns:
            item["result_columns"] = message.result_columns[:80]
            item["result_rows"] = message.result_rows[:MAX_CONTEXT_ROWS]
            item["row_count"] = message.row_count
        context_messages.append(item)
    return (
        "Current user follow-up: "
        + json.dumps(question, ensure_ascii=False)
        + "\nPrior turns from this conversation: "
        + json.dumps(context_messages, ensure_ascii=False, separators=(",", ":"))
        + "\nActive filters to preserve unless the user explicitly changes them: "
        + json.dumps(active_filters, ensure_ascii=False, separators=(",", ":"))
        + "\nUse the same authorized database and company scope. Resolve references such as "
        "'that', 'those', or 'same period' from the prior turns."
    )
