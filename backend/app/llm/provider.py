from dataclasses import dataclass
from typing import Literal

import httpx

from app.core.config import Settings, get_settings
from app.llm.models import ModelRegistry

Task = Literal["sql", "reasoning", "fast"]
TASK_SETTING = {"sql": "sql_model", "reasoning": "reasoning_model", "fast": "fast_model"}


class ProviderConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


class OpenRouterProvider:
    """Small OpenAI-compatible OpenRouter client with bounded model fallbacks."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.transport = transport

    def configuration_status(self) -> tuple[bool, int]:
        """Report readiness without exposing the configured key or model names."""
        key = (
            self.settings.openrouter_api_key.get_secret_value()
            if self.settings.openrouter_api_key
            else ""
        )
        if not key:
            return False, 0
        try:
            registry = ModelRegistry.load(self.settings.model_registry_path)
        except ValueError:
            return False, 0
        configured_count = 0
        for task, setting_name in TASK_SETTING.items():
            model_id = getattr(self.settings, setting_name)
            if not model_id:
                continue
            entry = registry.get(model_id)
            if entry is not None and task in entry.tasks:
                configured_count += 1
        return configured_count > 0, configured_count

    def _configuration(self, task: Task) -> tuple[str, list[str]]:
        key = (
            self.settings.openrouter_api_key.get_secret_value()
            if self.settings.openrouter_api_key
            else ""
        )
        if not key:
            raise ProviderConfigurationError("OPENROUTER_API_KEY is not configured")
        configured_model = getattr(self.settings, TASK_SETTING[task])
        if not configured_model:
            raise ProviderConfigurationError(f"No model is configured for the {task} task")
        try:
            registry = ModelRegistry.load(self.settings.model_registry_path)
        except ValueError as exc:
            raise ProviderConfigurationError(str(exc)) from exc
        entry = registry.get(configured_model)
        if entry is None or task not in entry.tasks:
            raise ProviderConfigurationError(
                f"Model {configured_model!r} is not registered for the {task} task"
            )
        fallbacks = registry.fallback_chain(configured_model)[1:]
        return key, [configured_model, *fallbacks]

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        task: Task = "fast",
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> ChatResult:
        api_key, model_chain = self._configuration(task)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.settings.openrouter_site_url,
            "X-Title": self.settings.openrouter_app_name,
        }
        last_error: Exception | None = None
        async with httpx.AsyncClient(
            base_url=self.settings.openrouter_base_url,
            timeout=httpx.Timeout(45.0, connect=8.0),
            transport=self.transport,
        ) as client:
            for model_id in model_chain[:3]:
                try:
                    response = await client.post(
                        "chat/completions",
                        headers=headers,
                        json={
                            "model": model_id,
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                    )
                    if response.status_code in {429, 500, 502, 503, 504}:
                        last_error = httpx.HTTPStatusError(
                            "OpenRouter temporary failure",
                            request=response.request,
                            response=response,
                        )
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    choice = payload["choices"][0]["message"]["content"]
                    if not isinstance(choice, str):
                        raise TypeError("OpenRouter returned an unsupported content shape")
                    usage = payload.get("usage") or {}
                    return ChatResult(
                        content=choice,
                        model=str(payload.get("model") or model_id),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        total_tokens=usage.get("total_tokens"),
                    )
                except (
                    httpx.RequestError,
                    httpx.HTTPStatusError,
                    KeyError,
                    IndexError,
                    ValueError,
                ) as exc:
                    last_error = exc
                    if (
                        isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code < 500
                        and exc.response.status_code != 429
                    ):
                        raise ProviderConfigurationError(
                            f"OpenRouter rejected the request ({exc.response.status_code})"
                        ) from exc
        raise ProviderConfigurationError(
            f"OpenRouter request failed for {len(model_chain[:3])} configured model attempt(s)"
        ) from last_error
