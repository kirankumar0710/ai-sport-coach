import pytest

from sport_coach.config import ConfigError, load_settings

TOML = """
[app]
data_dir = "data/workouts"
[llm]
default_provider = "gemini"
temperature = 0.3
[llm.providers.gemini]
model = "gemini-2.5-flash"
api_key_env = "GEMINI_API_KEY"
[llm.providers.anthropic]
model = "claude-sonnet-5-5"
api_key_env = "ANTHROPIC_API_KEY"
temperature = 0.7
"""


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "settings.toml"
    p.write_text(TOML)
    return p


def test_default_provider(cfg):
    s = load_settings(cfg, env={"GEMINI_API_KEY": "g"})
    assert s.provider.name == "gemini"
    assert s.provider.api_key == "g"
    assert s.provider.temperature == 0.3


def test_provider_env_override_and_per_provider_params(cfg):
    s = load_settings(cfg, env={"PROVIDER": "Anthropic", "ANTHROPIC_API_KEY": "a"})
    assert s.provider.name == "anthropic"
    assert s.provider.model == "claude-sonnet-5-5"
    assert s.provider.temperature == 0.7


def test_model_env_override(cfg):
    s = load_settings(cfg, env={"MODEL": "gemini-2.5-pro", "GEMINI_API_KEY": "g"})
    assert s.provider.model == "gemini-2.5-pro"


def test_missing_key_is_reported_with_env_name(cfg):
    with pytest.raises(ConfigError, match="export ANTHROPIC_API_KEY"):
        load_settings(cfg, env={"PROVIDER": "anthropic"})


def test_unknown_provider(cfg):
    with pytest.raises(ConfigError, match="Unknown provider"):
        load_settings(cfg, env={"PROVIDER": "mistral"})


def test_api_key_not_in_repr(cfg):
    s = load_settings(cfg, env={"GEMINI_API_KEY": "super-secret"})
    assert "super-secret" not in repr(s)
