"""Provider abstraction: turn a ProviderConfig into something an ADK agent can use.

Agents never import a vendor SDK. They call `build_model(settings.provider)` and
get back either a Gemini model name (ADK's native path) or an ADK `BaseLlm`
adapter. Adding a provider = add a TOML section + register one builder here.
"""

from __future__ import annotations

import os
from typing import Callable, Union

from google.adk.models.base_llm import BaseLlm
from google.genai import types

from sport_coach.config import ConfigError, ProviderConfig

AdkModel = Union[str, BaseLlm]
_Builder = Callable[[ProviderConfig], AdkModel]
_BUILDERS: dict[str, _Builder] = {}


def register_provider(name: str) -> Callable[[_Builder], _Builder]:
    def decorator(fn: _Builder) -> _Builder:
        _BUILDERS[name] = fn
        return fn

    return decorator


def supported_providers() -> tuple[str, ...]:
    return tuple(sorted(_BUILDERS))


def build_model(cfg: ProviderConfig) -> AdkModel:
    try:
        builder = _BUILDERS[cfg.name]
    except KeyError:
        raise ConfigError(
            f"No adapter registered for provider '{cfg.name}'. "
            f"Supported: {', '.join(supported_providers())}"
        ) from None
    return builder(cfg)


def build_generation_config(
    cfg: ProviderConfig, temperature: float | None = None
) -> types.GenerateContentConfig | None:
    """Provider-neutral generation params; ADK maps them for every backend.

    `temperature` overrides the configured value for one agent (e.g. 0 for the
    deterministic header mapper). It is dropped for providers whose models
    don't accept a temperature (`supports_temperature = false` in settings.toml).
    """
    params = {
        "temperature": (temperature if temperature is not None else cfg.temperature)
        if cfg.supports_temperature
        else None,
        "max_output_tokens": cfg.max_output_tokens,
    }
    params = {k: v for k, v in params.items() if v is not None}
    return types.GenerateContentConfig(**params) if params else None


# --- Adapters ---------------------------------------------------------------


@register_provider("gemini")
def _gemini(cfg: ProviderConfig) -> AdkModel:
    # ADK's google-genai client reads GOOGLE_API_KEY. Bridge our configured var.
    if cfg.api_key:
        os.environ.setdefault("GOOGLE_API_KEY", cfg.api_key)
    return cfg.model


def _litellm(prefix: str, cfg: ProviderConfig) -> AdkModel:
    from google.adk.models.lite_llm import LiteLlm  # imported lazily: optional path

    kwargs: dict[str, object] = {}
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key
    if cfg.base_url:
        kwargs["api_base"] = cfg.base_url
    return LiteLlm(model=f"{prefix}/{cfg.model}", **kwargs)


@register_provider("anthropic")
def _anthropic(cfg: ProviderConfig) -> AdkModel:
    return _litellm("anthropic", cfg)


@register_provider("openai")
def _openai(cfg: ProviderConfig) -> AdkModel:
    return _litellm("openai", cfg)
