"""AI Sports Coach - web interface.

    streamlit run app.py
"""

from pathlib import Path

import streamlit as st

from sport_coach import ingest, workouts
from sport_coach.config import ConfigError, Settings, load_settings
from sport_coach.service import SyncCoachService
from sport_coach.ui import admin, chat, dashboard, uploads
from sport_coach.usage import UsageStore
from sport_coach.workouts import WorkoutDataError

ASSETS = Path(__file__).parent / "assets"
LOGO = str(ASSETS / "logo.png")          # full logo: page title, README
ICON = str(ASSETS / "icon.png")          # robot head: readable at small sizes (sidebar)
FAVICON = str(ASSETS / "favicon.png")    # robot head: browser tab

st.set_page_config(page_title="AI Sports Coach", page_icon=FAVICON, layout="wide")
st.logo(ICON, size="large", icon_image=ICON)


@st.cache_resource(show_spinner=False)
def get_usage_store(path: str) -> UsageStore:
    return UsageStore(path)


@st.cache_resource(show_spinner=False)
def get_coach(provider_label: str, _settings: Settings) -> SyncCoachService:
    """One coach per process and provider/model (keyed on the label)."""
    return SyncCoachService(_settings, get_usage_store(str(_settings.usage_db)))


def _coach_key(s: Settings) -> str:
    return f"{s.provider.name}/{s.provider.model}"


# The dashboard works without an API key; only chat (and AI header mapping) need one.
try:
    settings = load_settings(require_api_key=False)
except ConfigError as exc:
    st.error(f"Configuration error: {exc}")
    st.stop()

data_dir = settings.data_dir

# --- Sidebar: upload + file selection --------------------------------------
with st.sidebar:
    st.header("Workouts")

    upload = st.file_uploader(
        "Upload workouts (CSV or Excel)", type=list(ingest.UPLOAD_TYPES)
    )
    # With an API key, headers are mapped by the LLM; otherwise by built-in rules.
    coach = get_coach(_coach_key(settings), settings) if settings.provider.api_key else None
    uploads.handle(upload, data_dir, coach.map_headers if coach else None)

    with st.expander("Which files work?"):
        st.markdown(
            "Any CSV, TSV or Excel/ODS export with a header row: from a watch app, "
            "a spreadsheet or your own log, in any language. Columns are mapped to our "
            "template automatically and units are converted.  \n"
            "Needed: a **date** plus at least one measurement (distance, duration, pace, "
            "calories, heart rate, …). Panels for data your file doesn't have are left empty."
        )
        st.download_button(
            "Download our template", dashboard.template_csv(), "workouts_template.csv", "text/csv"
        )

    files = workouts.list_files(data_dir)
    if not files:
        st.info("Upload a CSV or Excel file to get started.")
        uploads.render_notice()
        st.stop()

    current = st.session_state.get("active_file")
    active_file = st.selectbox(
        "Workout file", files, index=files.index(current) if current in files else 0
    )
    st.session_state["active_file"] = active_file
    st.download_button(
        "Download this file", workouts.resolve_file(data_dir, active_file).read_bytes(),
        active_file, "text/csv", width="stretch",
    )

    st.divider()
    st.caption(f"Model: {settings.provider.name} · {settings.provider.model}")

# --- Main area -------------------------------------------------------------
title_logo, title_text = st.columns([1, 11], vertical_alignment="center")
title_logo.image(LOGO, width=84)
title_text.title(settings.app_name)

uploads.render_notice()

try:
    rows = workouts.load_workouts(data_dir, active_file)
except WorkoutDataError as exc:
    st.error(f"Could not read {active_file}: {exc}")
    st.stop()

tab_dash, tab_chat, tab_admin = st.tabs(["📊 Dashboard", "💬 Coach", "🛠️ Admin"])

with tab_dash:
    dashboard.render(rows)

with tab_chat:
    if not settings.provider.api_key:
        st.info(
            f"Chat is disabled: set `{settings.provider.api_key_env}` in your shell "
            "and restart the app."
        )
    else:
        chat.render(coach, active_file)

with tab_admin:
    admin.render(settings, get_usage_store(str(settings.usage_db)))
