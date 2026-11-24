"""OpenAI, through LiteLLM.

`base_url` in settings.toml points it at a proxy or an OpenAI-compatible
endpoint. Some OpenAI reasoning models reject temperature: set
`supports_temperature = false` under [llm.providers.openai] for those.
"""

from __future__ import annotations

from sport_coach.providers._litellm import LiteLlmProvider


class OpenAIProvider(LiteLlmProvider):
    name = "openai"
    prefix = "openai"
