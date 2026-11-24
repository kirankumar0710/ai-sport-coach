"""Upload handling: import automatically, then tell the user what happened."""

from pathlib import Path

import pandas as pd
import streamlit as st

from sport_coach import ingest
from sport_coach.ingest import HeaderMapper
from sport_coach.workouts import WorkoutDataError

_SOURCE = {
    "ai": "using AI",
    "ai+rules": "using AI and built-in rules",
    "rules": "using built-in rules",
}
CACHE_FILE = ".header_mappings.json"


def handle(upload, data_dir: Path, mapper: HeaderMapper | None) -> None:
    """Import an uploaded file once (Streamlit reruns keep the same upload)."""
    if upload is None or st.session_state.get("last_upload_id") == upload.file_id:
        return
    st.session_state["last_upload_id"] = upload.file_id
    try:
        with st.spinner(f"Importing {upload.name}…"):
            result = ingest.import_file(
                data_dir, upload.name, upload.getvalue(), mapper=mapper, cache_path=data_dir / CACHE_FILE
            )
    except WorkoutDataError as exc:
        st.session_state["import_notice"] = {"error": f"Couldn't import {upload.name}: {exc}"}
        return
    st.session_state["active_file"] = result.name
    st.session_state["import_notice"] = notice_for(upload.name, result)


def notice_for(upload_name: str, result: ingest.ImportResult) -> dict:
    """Plain-data summary of an import, kept in session state for the notice."""
    return {
        "upload": upload_name,
        "name": result.name,
        "count": result.count,
        "matched": result.matched_template,
        "source": result.mapping.source,
        "lines": result.messages(),
        "notes": result.mapping.notes,
        "skipped": result.conversion.skipped,
        "ignored": result.conversion.ignored_cells,
        "csv": result.csv_text,
    }


def _dismiss() -> None:
    st.session_state.pop("import_notice", None)


def render_notice() -> None:
    notice = st.session_state.get("import_notice")
    if not notice:
        return
    if "error" in notice:
        st.error(notice["error"])
        st.button("Dismiss", on_click=_dismiss, key="dismiss_import")
        return

    skipped = notice["skipped"]
    extra = f" {len(skipped)} row(s) were skipped." if skipped else ""
    if notice["matched"]:
        st.success(f"Imported {notice['count']} workouts into **{notice['name']}**.{extra}")
        if not skipped:
            _dismiss()  # nothing to explain next time
            return
    else:
        with st.container(border=True):
            st.markdown(
                f"**Your file “{notice['upload']}” didn't match our template, so we mapped it "
                f"automatically** ({_SOURCE.get(notice['source'], '')}). "
                f"Imported {notice['count']} workouts into **{notice['name']}**.{extra}"
            )
            st.markdown("\n".join(f"- {line}" for line in notice["lines"]))
            if notice["notes"]:
                st.caption(" ".join(notice["notes"]))
            if notice["ignored"]:
                st.caption(f"{notice['ignored']} cell(s) couldn't be read and were left empty.")
            a = st.columns([2, 1, 4])
            a[0].download_button(
                "Download processed CSV", notice["csv"], notice["name"], "text/csv",
                type="primary", width="stretch",
            )
            a[1].button("Dismiss", on_click=_dismiss, key="dismiss_import", width="stretch")

    if skipped:
        with st.expander(f"Skipped rows ({len(skipped)})"):
            st.dataframe(pd.DataFrame(skipped, columns=["row", "reason"]), hide_index=True, width="stretch")
