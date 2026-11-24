"""Google Gemini: native in ADK, no adapter library needed.

ADK resolves a Gemini model name (e.g. "gemini-2.5-flash") to its built-in
Gemini model, which calls the Gemini API through the google-genai SDK.
"""

from __future__ import annotations

import os

from sport_coach.config import ProviderConfig
from sport_coach.providers.base import AdkModel, Provider


class GeminiProvider(Provider):
    name = "gemini"

    def build_model(self, cfg: ProviderConfig) -> AdkModel:
        # The google-genai SDK reads GOOGLE_API_KEY; we configure GEMINI_API_KEY.
        if cfg.api_key:
            os.environ.setdefault("GOOGLE_API_KEY", cfg.api_key)
        return cfg.model
