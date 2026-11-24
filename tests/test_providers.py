import pytest
from google.adk.models.lite_llm import LiteLlm

from sport_coach.config import ConfigError, ProviderConfig, load_settings
from sport_coach.providers import (
    PROVIDERS, Provider, build_generation_config, build_model, get_provider, supported_providers,
)
from sport_coach.providers.anthropic import AnthropicProvider
from sport_coach.providers.gemini import GeminiProvider
from sport_coach.providers.openai import OpenAIProvider


def cfg(name, model="m", **kw):
    return ProviderConfig(name, model, f"{name.upper()}_API_KEY", "k", **kw)


# --- Registry -------------------------------------------------------------------


def test_one_adapter_per_vendor():
    assert supported_providers() == ("anthropic", "gemini", "openai")
    assert isinstance(get_provider("gemini"), GeminiProvider)
    assert isinstance(get_provider("anthropic"), AnthropicProvider)
    assert isinstance(get_provider("openai"), OpenAIProvider)
    assert all(isinstance(p, Provider) and p.name == n for n, p in PROVIDERS.items())


def test_unknown_provider():
    with pytest.raises(ConfigError, match="No adapter for provider 'mistral'"):
        build_model(cfg("mistral"))


# --- Models -----------------------------------------------------------------------


def test_gemini_is_native_model_name(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert build_model(cfg("gemini", "gemini-2.5-flash")) == "gemini-2.5-flash"
    import os
    assert os.environ["GOOGLE_API_KEY"] == "k"  # key handed to the google-genai SDK


def test_anthropic_and_openai_use_litellm():
    a = build_model(cfg("anthropic", "claude-sonnet-5-5"))
    o = build_model(cfg("openai", "gpt-4.1", base_url="https://proxy.example/v1"))
    assert isinstance(a, LiteLlm) and a.model == "anthropic/claude-sonnet-5-5"
    assert isinstance(o, LiteLlm) and o.model == "openai/gpt-4.1"


# --- Generation settings: vendor default + settings.toml override ------------------


def test_generation_config_passes_configured_values():
    gc = build_generation_config(cfg("gemini", temperature=0.2, max_output_tokens=100))
    assert gc.temperature == 0.2 and gc.max_output_tokens == 100


def test_per_agent_temperature_override_where_supported():
    gemini = cfg("gemini", temperature=0.3)
    assert build_generation_config(gemini).temperature == 0.3
    assert build_generation_config(gemini, temperature=0).temperature == 0


def test_anthropic_default_sends_no_temperature():
    claude = cfg("anthropic", temperature=0.3, max_output_tokens=100)
    assert build_generation_config(claude).temperature is None
    assert build_generation_config(claude, temperature=0).temperature is None
    assert build_generation_config(claude).max_output_tokens == 100


def test_settings_override_vendor_default_both_ways():
    old_claude = cfg("anthropic", temperature=0.3, supports_temperature=True)
    assert build_generation_config(old_claude).temperature == 0.3
    reasoning_openai = cfg("openai", temperature=0.3, max_output_tokens=100, supports_temperature=False)
    assert build_generation_config(reasoning_openai).temperature is None


def test_shipped_settings_use_vendor_defaults():
    claude = load_settings(env={"PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k"}).provider
    gemini = load_settings(env={"PROVIDER": "gemini", "GEMINI_API_KEY": "k"}).provider
    assert claude.supports_temperature is None and gemini.supports_temperature is None
    assert build_generation_config(claude).temperature is None
    assert build_generation_config(gemini).temperature == 0.3


def test_quoted_boolean_in_settings_is_rejected(tmp_path):
    p = tmp_path / "s.toml"
    p.write_text('[llm]\ndefault_provider = "openai"\n[llm.providers.openai]\n'
                 'model = "gpt-4.1"\nsupports_temperature = "false"\n')
    with pytest.raises(ConfigError, match="must be true or false"):
        load_settings(p, env={"OPENAI_API_KEY": "k"})
