# AI Sports Coach

A multi-agent AI running coach built on a provider-agnostic agent harness.
Cycle 1 uses **Google ADK** as the harness. **Gemini** runs natively, and
**Anthropic** and **OpenAI** run through ADK's LiteLLM adapter.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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
streamlit run app.py                  # web app: upload, dashboard, coach chat
python -m sport_coach.cli --trace     # console chat (prints tool calls)
```

The web app has:
- **Upload**: a workout CSV in the sidebar. It's validated before saving; invalid files are rejected with the line number.
- **Dashboard**: workouts, distance, time, average pace, workouts per week and longest run.
  Charts show weekly distance (weeks with more than a 10% jump are flagged), pace per run,
  long-run progression and workouts per week, with a period filter and table views.
- **Coach**: chat with the agent about the selected file, with live tool-call status.

The dashboard works without an API key; only the chat needs one.

### Workout CSV format

| column | required | example |
|---|---|---|
| `date` | yes | `2026-09-01` |
| `distance_km` | yes | `5.0` |
| `duration_min` | yes | `29.5` |
| `activity` | no | `run` |
| `calories` | no | `360` |

Uploads are saved in `data/workouts/`. Git ignores them because they're personal data;
only `sample_runs.csv` is tracked.

## Architecture

```
app.py (Streamlit) / sport_coach/cli.py      our interfaces: no ADK imports
            │  CoachEvent (tool_call / tool_result / message)
sport_coach/service.py   CoachService        application layer; the only place that knows ADK
            │
ADK Runner + workout_agent                   harness (replaceable)
            │                    │
llm/factory.py               tools/workout_tools.py → workouts.py
(Gemini | LiteLLM)           (deterministic statistics, shared with the dashboard)
```

## Layout

```
app.py                          Streamlit entry point
requirements.txt                dependencies
config/settings.toml            vendors, models, params (no secrets)
sport_coach/config.py           TOML + env loading → Settings
sport_coach/service.py          CoachService (async) + SyncCoachService (for Streamlit)
sport_coach/workouts.py         CSV parsing, validation, storage, statistics
sport_coach/llm/factory.py      provider registry → ADK model (native Gemini / LiteLlm)
sport_coach/tools/              function tools wrapping workouts.py
sport_coach/agents/             agents (Phase 1: workout_agent)
sport_coach/ui/                 dashboard and chat components
sport_coach/cli.py              console interface
data/workouts/                  workout CSVs
```

### Adding a provider

1. Add a `[llm.providers.<name>]` section to `settings.toml`.
2. Register a builder in `llm/factory.py` with `@register_provider("<name>")`.

You don't need to change any agents, tools or UI.

## Tests

```bash
pytest
```
