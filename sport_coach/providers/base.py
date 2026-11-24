"""The provider interface: what every vendor adapter gives the agent harness.

A provider turns a ProviderConfig (settings.toml + env vars) into:
  - a model ADK can run (`build_model`)
  - generation settings that vendor accepts (`generation_config`)

Subclasses set `name`, implement `build_model`, and override other members only
where their vendor differs. These adapters return ADK model objects, so they are
ADK provider adapters: a different harness would need its own `build_model`.
"""

from __future__ import annotations

from typing import Union

from google.adk.models.base_llm import BaseLlm
from google.genai import types

from sport_coach.config import ProviderConfig

AdkModel = Union[str, BaseLlm]  # a model name ADK resolves itself, or an ADK model wrapper


class Provider:
    name: str = ""
    # Vendor default. Model limits really belong to the model, so settings.toml
    # can override it per provider with `supports_temperature = true|false`.
    supports_temperature: bool = True

    def build_model(self, cfg: ProviderConfig) -> AdkModel:
        raise NotImplementedError

    def allows_temperature(self, cfg: ProviderConfig) -> bool:
        if cfg.supports_temperature is not None:  # explicit setting in settings.toml wins
            return cfg.supports_temperature
        return self.supports_temperature

    def generation_config(
        self, cfg: ProviderConfig, temperature: float | None = None
    ) -> types.GenerateContentConfig | None:
        """Generation params for one agent; ADK maps them for every backend.

        `temperature` overrides the configured value for one agent (e.g. 0 for
        the header mapper). It is dropped when the model doesn't accept one.
        """
        params = {
            "temperature": (temperature if temperature is not None else cfg.temperature)
            if self.allows_temperature(cfg)
            else None,
            "max_output_tokens": cfg.max_output_tokens,
        }
        params = {k: v for k, v in params.items() if v is not None}
        return types.GenerateContentConfig(**params) if params else None
