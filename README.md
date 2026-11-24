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
- **Upload**: any workout CSV/TSV or Excel/ODS export in the sidebar. If it doesn't match our template,
  it is mapped automatically and you get a summary of the mapping plus a download of the processed CSV.
- **Dashboard**: headline numbers and charts (weekly distance with >10% jumps flagged, pace, long run,
  frequency, training time, calories, heart rate, elevation, cadence). Each panel needs certain
  template fields; panels for data your file doesn't have are shown as placeholders.
- **Coach**: chat with the agent about the selected file, with live tool-call status.

The dashboard works without an API key; only the chat needs one.

### Workout template

The app stores every file in one CSV template ([sport_coach/schema.py](sport_coach/schema.py)):

`date, activity, distance_km, duration_min, pace_min_per_km, calories, avg_hr, max_hr, elevation_gain_m, cadence_spm, notes`

Only `date` plus one measurement is required; any other column can be empty.

### Importing workouts

Upload any table with a header row: a watch-app export, a spreadsheet or your own log,
in any language ([sport_coach/ingest.py](sport_coach/ingest.py)):

1. **Read**: CSV/TSV/TXT (any delimiter or encoding) or Excel/ODS. Title rows above the header are ignored.
2. **Already our template?** Then it's imported as is.
3. **Otherwise, map headers to the template**:
   - with an API key, the **Header Mapper agent** (LLM, structured output) gets the headers plus
     5 sample rows and returns which column fills each template field and its unit. Answers are cached
     per header set, so a given export format costs one model call.
   - **built-in rules** (synonyms, close spelling) fill any gaps, and do all the mapping without a key.
   - every match is checked against the column's values, so a wrong guess is dropped.
4. **Copy the data into the template in Python**: unit conversion (km/mi/m, min/s/h, h:mm:ss, pace,
   ft), date formats, Excel cells. Pace, duration or distance are calculated when two of them are known.
   The LLM never touches the values.
5. **Save and report**: "Your file didn't match our template, so we mapped it automatically", listing
   what was mapped, what was calculated, what isn't in the file and which rows were skipped (e.g. a
   `TOTAL` row), with a **Download processed CSV** button.

Header names and 5 sample rows are sent to the configured LLM provider when an API key is set.
Imports are saved in `data/workouts/`; git ignores them because they're personal data, and
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
sport_coach/schema.py           the workout template (single source of truth)
sport_coach/ingest.py           import: read any table, map headers (AI + rules), convert into the template
sport_coach/workouts.py         canonical CSV parsing, validation, storage, statistics
sport_coach/llm/factory.py      provider registry → ADK model (native Gemini / LiteLlm)
sport_coach/tools/              function tools wrapping workouts.py
sport_coach/agents/             workout_agent (coach), header_mapper (import)
sport_coach/ui/                 dashboard, upload notice and chat components
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
