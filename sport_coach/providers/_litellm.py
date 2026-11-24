"""Shared base for vendors ADK reaches through LiteLLM (Anthropic, OpenAI, ...)."""

from __future__ import annotations

from sport_coach.config import ProviderConfig
from sport_coach.providers.base import AdkModel, Provider


class LiteLlmProvider(Provider):
    prefix: str = ""  # LiteLLM model prefix, e.g. "anthropic" -> "anthropic/<model>"

    def build_model(self, cfg: ProviderConfig) -> AdkModel:
        from google.adk.models.lite_llm import LiteLlm  # imported lazily: only these vendors need it

        kwargs: dict[str, object] = {}
        if cfg.api_key:
            kwargs["api_key"] = cfg.api_key
        if cfg.base_url:
            kwargs["api_base"] = cfg.base_url
        return LiteLlm(model=f"{self.prefix}/{cfg.model}", **kwargs)
