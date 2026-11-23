# AI Sports Coach

A multi-agent AI running coach built on a provider-agnostic agent harness.
Cycle 1 uses **Google ADK** as the harness. **Gemini** runs natively, and
**Anthropic** and **OpenAI** run through ADK's LiteLLM adapter.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Configuration

Settings that aren't secret live in [`config/settings.toml`](config/settings.toml):
the vendors, their models, generation parameters and the data directory.
Secrets and the provider choice come from your shell:

```bash
export PROVIDER=gemini            # gemini | anthropic | openai (overrides default_provider)
export GEMINI_API_KEY=...
export ANTHROPIC_API_KEY=...      # only needed when PROVIDER=anthropic
export OPENAI_API_KEY=...         # only needed when PROVIDER=openai
export MODEL=gemini-2.5-pro       # optional: override the provider's model
export SPORT_COACH_CONFIG=...     # optional: use another TOML file
```

The TOML file only stores the *name* of each key's environment variable
(`api_key_env`), never the key itself.

## Run

```bash
.venv/bin/sport-coach              # console chat via the ADK Runner
.venv/bin/sport-coach --trace      # also print tool calls and results
.venv/bin/adk web adk_apps         # ADK dev UI (run from the repo root)
```

Try: *"Analyse my workouts and tell me how consistent I've been."*

## Layout

```
config/settings.toml            vendors, models, params (no secrets)
src/sport_coach/config.py       TOML + env loading → Settings
src/sport_coach/llm/factory.py  provider registry → ADK model (native Gemini / LiteLlm)
src/sport_coach/tools/          deterministic workout analytics (function tools)
src/sport_coach/agents/         agents (Phase 1: workout_agent)
src/sport_coach/cli.py          Runner + session + event loop
adk_apps/coach/                 `root_agent` entry point for `adk web` / `adk run`
data/workouts/                  workout CSVs (date, activity, distance_km, duration_min, calories)
```

### Adding a provider

1. Add a `[llm.providers.<name>]` section to `settings.toml`.
2. Register a builder in `llm/factory.py` with `@register_provider("<name>")`.

You don't need to change any agents or tools.

## Tests

```bash
.venv/bin/pytest
```
