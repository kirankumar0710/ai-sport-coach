"""LLM providers: one adapter per vendor, behind one small interface.

Agents never import a vendor SDK. They call `build_model(settings.provider)` and
`build_generation_config(settings.provider)`; the adapter for the configured
vendor (PROVIDER env var / settings.toml) handles that vendor's specifics.

Adding a vendor:
  1. create providers/<vendor>.py with a Provider subclass
  2. add it to PROVIDERS below
  3. add an [llm.providers.<vendor>] section to settings.toml
"""

from __future__ import annotations

from google.genai import types

from sport_coach.config import ConfigError, ProviderConfig
from sport_coach.providers.anthropic import AnthropicProvider
from sport_coach.providers.base import AdkModel, Provider
from sport_coach.providers.gemini import GeminiProvider
from sport_coach.providers.openai import OpenAIProvider

PROVIDERS: dict[str, Provider] = {
    p.name: p for p in (GeminiProvider(), AnthropicProvider(), OpenAIProvider())
}


def supported_providers() -> tuple[str, ...]:
    return tuple(sorted(PROVIDERS))


def get_provider(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ConfigError(
            f"No adapter for provider '{name}'. Supported: {', '.join(supported_providers())}"
        ) from None


def build_model(cfg: ProviderConfig) -> AdkModel:
    return get_provider(cfg.name).build_model(cfg)


def build_generation_config(
    cfg: ProviderConfig, temperature: float | None = None
) -> types.GenerateContentConfig | None:
    return get_provider(cfg.name).generation_config(cfg, temperature)


__all__ = [
    "AdkModel", "PROVIDERS", "Provider", "build_generation_config", "build_model",
    "get_provider", "supported_providers",
]
