from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str
    tasks: list[str]
    input_usd_per_million_tokens: float | None = Field(default=None, ge=0)
    output_usd_per_million_tokens: float | None = Field(default=None, ge=0)
    fallbacks: list[str] = Field(default_factory=list)


class ModelRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    provider: str
    models: list[ModelEntry]

    @classmethod
    def load(cls, path: Path) -> "ModelRegistry":
        import json

        try:
            return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError) as exc:
            raise ValueError(f"Could not load model registry at {path}: {exc}") from exc

    def get(self, model_id: str) -> ModelEntry | None:
        return next((model for model in self.models if model.id == model_id), None)

    def fallback_chain(self, model_id: str, max_attempts: int = 3) -> list[str]:
        ordered: list[str] = []
        pending = [model_id]
        while pending and len(ordered) < max_attempts:
            current = pending.pop(0)
            if current in ordered:
                continue
            model = self.get(current)
            if model is None:
                continue
            ordered.append(current)
            pending.extend(model.fallbacks)
        return ordered
