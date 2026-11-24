"""Application settings: non-secret config from TOML, secrets and overrides from env.

Precedence (highest first):
  1. Environment variables: PROVIDER, MODEL, <provider api_key_env>
  2. config/settings.toml (or the file named by SPORT_COACH_CONFIG)
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.toml"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    """Everything needed to talk to one LLM vendor."""

    name: str
    model: str
    api_key_env: str
    api_key: str | None = field(default=None, repr=False)  # never print secrets
    base_url: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    # None = use the vendor default (providers/<vendor>.py); true/false in
    # settings.toml overrides it, e.g. for a model that rejects temperature.
    supports_temperature: bool | None = None


@dataclass(frozen=True)
class Settings:
    app_name: str
    data_dir: Path
    provider: ProviderConfig
    available_providers: tuple[str, ...]


def load_settings(
    config_path: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    require_api_key: bool = True,
) -> Settings:
    env = os.environ if env is None else env
    path = Path(config_path or env.get("SPORT_COACH_CONFIG") or DEFAULT_CONFIG_PATH)
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    app = raw.get("app", {})
    llm = raw.get("llm", {})
    providers: dict[str, Any] = llm.get("providers", {})
    if not providers:
        raise ConfigError("No providers defined under [llm.providers.*]")

    name = (env.get("PROVIDER") or llm.get("default_provider") or "").strip().lower()
    if name not in providers:
        raise ConfigError(
            f"Unknown provider '{name}'. Configured providers: {', '.join(sorted(providers))}"
        )

    p = providers[name]
    model = (env.get("MODEL") or p.get("model") or "").strip()
    if not model:
        raise ConfigError(f"No model set for provider '{name}'")

    key_env = p.get("api_key_env") or f"{name.upper()}_API_KEY"
    api_key = env.get(key_env)
    if require_api_key and not api_key:
        raise ConfigError(
            f"Provider '{name}' needs an API key. Run: export {key_env}=<your key>"
        )

    supports_temperature = p.get("supports_temperature")
    if supports_temperature is not None and not isinstance(supports_temperature, bool):
        raise ConfigError(
            f"supports_temperature for '{name}' must be true or false (no quotes), "
            f"got {supports_temperature!r}"
        )

    data_dir = Path(app.get("data_dir", "data/workouts"))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir

    return Settings(
        app_name=app.get("name", "AI Sports Coach"),
        data_dir=data_dir,
        provider=ProviderConfig(
            name=name,
            model=model,
            api_key_env=key_env,
            api_key=api_key,
            base_url=p.get("base_url"),
            temperature=p.get("temperature", llm.get("temperature")),
            max_output_tokens=p.get("max_output_tokens", llm.get("max_output_tokens")),
            supports_temperature=supports_temperature,
        ),
        available_providers=tuple(sorted(providers)),
    )
