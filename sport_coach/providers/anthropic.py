"""Anthropic Claude, through LiteLLM.

Current Claude models reject sampling parameters (temperature, top_p): only the
model default is accepted, and LiteLLM raises UnsupportedParamsError otherwise.
So no temperature is sent by default. For an older Claude model that accepts
one, set `supports_temperature = true` under [llm.providers.anthropic].
"""

from __future__ import annotations

from sport_coach.providers._litellm import LiteLlmProvider


class AnthropicProvider(LiteLlmProvider):
    name = "anthropic"
    prefix = "anthropic"
    supports_temperature = False
