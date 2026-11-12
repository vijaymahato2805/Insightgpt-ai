from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.llm.models import ModelRegistry
from app.llm.provider import OpenRouterProvider, ProviderConfigurationError


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, app_env="test", **kwargs)


def test_openrouter_url_configuration_is_validated():
    configured = _settings(openrouter_base_url="https://openrouter.ai/api/v1/")
    assert configured.openrouter_base_url == "https://openrouter.ai/api/v1"
    with pytest.raises(ValidationError):
        _settings(openrouter_base_url="file:///etc/passwd")


def test_model_registry_loads_and_resolves_a_bounded_fallback_chain():
    registry = ModelRegistry.load(Path(__file__).parents[2] / "config" / "model_registry.json")
    assert registry.provider == "openrouter"
    assert registry.fallback_chain("openai/gpt-4.1-mini") == [
        "openai/gpt-4.1-mini",
        "google/gemini-2.5-flash",
    ]


@pytest.mark.asyncio
async def test_provider_requires_a_key_and_task_model():
    with pytest.raises(ProviderConfigurationError, match="OPENROUTER_API_KEY"):
        await OpenRouterProvider(_settings()).chat_completion([{"role": "user", "content": "Hi"}])

    configured = _settings(openrouter_api_key=SecretStr("test-key"))
    with pytest.raises(ProviderConfigurationError, match="No model is configured"):
        await OpenRouterProvider(configured).chat_completion(
            [{"role": "user", "content": "Hi"}], task="fast"
        )


@pytest.mark.asyncio
async def test_provider_uses_configured_fallback_and_tracks_token_usage():
    seen_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = request.read().decode()
        if "openai/gpt-4.1-mini" in model:
            seen_models.append("openai/gpt-4.1-mini")
            return httpx.Response(503, json={"error": "temporary"}, request=request)
        seen_models.append("google/gemini-2.5-flash")
        return httpx.Response(
            200,
            json={
                "model": "google/gemini-2.5-flash",
                "choices": [{"message": {"content": "Ready."}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            },
            request=request,
        )

    settings = _settings(openrouter_api_key=SecretStr("test-key"), fast_model="openai/gpt-4.1-mini")
    result = await OpenRouterProvider(
        settings, transport=httpx.MockTransport(handler)
    ).chat_completion([{"role": "user", "content": "Status?"}], task="fast")
    assert seen_models == ["openai/gpt-4.1-mini", "google/gemini-2.5-flash"]
    assert result.content == "Ready."
    assert result.total_tokens == 9
