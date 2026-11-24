"""AI Sports Coach - web interface.

    streamlit run app.py
"""

import streamlit as st

from sport_coach import workouts
from sport_coach.config import ConfigError, Settings, load_settings
from sport_coach.service import SyncCoachService
from sport_coach.ui import chat, dashboard
from sport_coach.workouts import WorkoutDataError

st.set_page_config(page_title="AI Sports Coach", page_icon="🏃", layout="wide")


@st.cache_resource(show_spinner=False)
def get_coach(provider_label: str, _settings: Settings) -> SyncCoachService:
    """One coach per process and provider/model (keyed on the label)."""
    return SyncCoachService(_settings)


# The dashboard works without an API key; only chat needs one.
try:
    settings = load_settings(require_api_key=False)
except ConfigError as exc:
    st.error(f"Configuration error: {exc}")
    st.stop()

data_dir = settings.data_dir

# --- Sidebar: upload + file selection --------------------------------------
with st.sidebar:
    st.header("🏃 Workouts")

    upload = st.file_uploader("Upload a workout CSV", type=["csv"])
    if upload is not None and st.session_state.get("last_upload_id") != upload.file_id:
        st.session_state["last_upload_id"] = upload.file_id
        try:
            name, count = workouts.save_upload(data_dir, upload.name, upload.getvalue())
            st.session_state["active_file"] = name
            st.success(f"Saved **{name}** ({count} workouts)")
        except WorkoutDataError as exc:
            st.error(f"Upload rejected: {exc}")

    with st.expander("Expected CSV format"):
        st.markdown(
            "Required columns: `date` (YYYY-MM-DD), `distance_km`, `duration_min`  \n"
            "Optional: `activity`, `calories`"
        )
        st.download_button(
            "Download template", dashboard.sample_csv(), "workouts_template.csv", "text/csv"
        )

    files = workouts.list_files(data_dir)
    if not files:
        st.info("Upload a CSV to get started.")
        st.stop()

    current = st.session_state.get("active_file")
    active_file = st.selectbox(
        "Workout file", files, index=files.index(current) if current in files else 0
    )
    st.session_state["active_file"] = active_file

    st.divider()
    st.caption(f"Model: {settings.provider.name} · {settings.provider.model}")

# --- Main area -------------------------------------------------------------
st.title(settings.app_name)

try:
    rows = workouts.load_workouts(data_dir, active_file)
except WorkoutDataError as exc:
    st.error(f"Could not read {active_file}: {exc}")
    st.stop()

tab_dash, tab_chat = st.tabs(["📊 Dashboard", "💬 Coach"])

with tab_dash:
    dashboard.render(rows)

with tab_chat:
    if not settings.provider.api_key:
        st.info(
            f"Chat is disabled: set `{settings.provider.api_key_env}` in your shell "
            "and restart the app."
        )
    else:
        coach = get_coach(f"{settings.provider.name}/{settings.provider.model}", settings)
        chat.render(coach, active_file)
