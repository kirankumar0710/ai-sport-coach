"""Workout statistics dashboard (Streamlit + Altair).

Panels declare the template fields they need; a file's available fields decide
which panels render and which show a "not in this file" placeholder.

All numbers come from sport_coach.workouts - the same functions the agent's
tools use - so the dashboard and the coach never disagree.
"""

from dataclasses import dataclass
from datetime import date
from typing import Callable

import altair as alt
import pandas as pd
import streamlit as st

from sport_coach import workouts
from sport_coach.schema import COLUMNS, FIELDS

# Reference palette: one series hue + the reserved status "warning" colour.
_SERIES = {"light": "#2a78d6", "dark": "#3987e5"}
_WARNING = "#fab219"
_JUMP = f">{workouts.VOLUME_JUMP_WARN_PCT:.0f}% jump"


# Chart labels: a mid-grey that stays readable on both light and dark surfaces
# (the reported theme isn't reliable enough to switch colours on).
_LABEL = "#8a8a85"

# Chart panels: rounded card, neutral edge and a soft shadow. Translucent
# colours keep it working in both themes without detecting which is active.
_PANEL_CSS = """
        border: 1px solid rgba(128, 128, 128, .28) !important;
        box-shadow: 0 1px 2px rgba(0, 0, 0, .14), 0 6px 18px rgba(0, 0, 0, .16);"""


def _theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except AttributeError:  # older Streamlit without st.context.theme
        return "light"


def _series_color() -> str:
    return _SERIES[_theme()]


def _inject_panel_css() -> None:
    st.html(f"""<style>
    [class*="st-key-panel-"] {{
        border-radius: 14px !important;{_PANEL_CSS}
        padding: 16px 18px 8px !important;
    }}
    [class*="st-key-panel-ph-"] {{ opacity: .6; box-shadow: none; }}
    </style>""")


def _fmt_duration(minutes: float) -> str:
    h, m = divmod(round(minutes), 60)
    return f"{h}h {m:02d}m"


# --- Chart builders ------------------------------------------------------------

_WEEK_X = alt.X("week_start:T", title=None, axis=alt.Axis(format="%d %b", grid=False))
_DAY_X = alt.X("date:T", title=None, axis=alt.Axis(format="%d %b", grid=False))


def _week_tooltip(field: str, title: str, fmt: str = ".1f") -> list:
    return [alt.Tooltip("week:N", title="Week"), alt.Tooltip(f"{field}:Q", title=title, format=fmt),
            alt.Tooltip("workouts:Q", title="Workouts")]


def _weekly_bars(wdf: pd.DataFrame, field: str, title: str, color: str, fmt: str = ".1f") -> alt.Chart:
    return (
        alt.Chart(wdf.dropna(subset=[field]))
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=18, color=color)
        .encode(x=_WEEK_X, y=alt.Y(f"{field}:Q", title=None), tooltip=_week_tooltip(field, title, fmt))
    )


def _per_workout_line(rdf: pd.DataFrame, field: str, title: str, color: str,
                      reverse: bool = False, text_field: str | None = None) -> alt.Chart:
    tip = [alt.Tooltip("date:T", title="Date", format="%a %d %b %Y")]
    tip.append(alt.Tooltip(f"{text_field}:N", title=title) if text_field
               else alt.Tooltip(f"{field}:Q", title=title, format=".0f"))
    if "distance_km" in rdf:
        tip.append(alt.Tooltip("distance_km:Q", title="Distance (km)", format=".1f"))
    return (
        alt.Chart(rdf.dropna(subset=[field]))
        .mark_line(point=alt.OverlayMarkDef(size=64, filled=True), strokeWidth=2, color=color)
        .encode(x=_DAY_X, y=alt.Y(f"{field}:Q", title=None, scale=alt.Scale(reverse=reverse, zero=False)),
                tooltip=tip)
    )


def _weekly_distance(wdf, rdf, color):
    bars = (
        alt.Chart(wdf.dropna(subset=["distance_km"]))
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=18)
        .encode(
            x=_WEEK_X,
            y=alt.Y("distance_km:Q", title=None),
            color=alt.Color("status:N", scale=alt.Scale(domain=["OK", _JUMP], range=[color, _WARNING]),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=_week_tooltip("distance_km", "Distance (km)") + [alt.Tooltip("change:N", title="vs previous week")],
        )
    )
    labels = (
        alt.Chart(wdf[wdf["volume_jump_warning"]])
        .mark_text(dy=-8, fontSize=11, fontWeight="bold", color=_LABEL)
        .encode(x=_WEEK_X, y="distance_km:Q", text=alt.Text("change:N"))
    )
    return bars + labels


@dataclass(frozen=True)
class Panel:
    title: str
    needs: frozenset[str]
    build: Callable[[pd.DataFrame, pd.DataFrame, str], alt.Chart]


PANELS: tuple[Panel, ...] = (
    Panel("Weekly distance (km)", frozenset({"distance_km"}), _weekly_distance),
    Panel("Pace per workout (min/km, faster ↑)", frozenset({"pace_min_per_km"}),
          lambda w, r, c: _per_workout_line(r, "pace_min_per_km", "Pace", c, reverse=True, text_field="pace")),
    Panel("Long run per week (km)", frozenset({"distance_km"}),
          lambda w, r, c: _weekly_bars(w, "long_run_km", "Long run (km)", c)),
    Panel("Workouts per week", frozenset(),
          lambda w, r, c: _weekly_bars(w, "workouts", "Workouts", c, ".0f")),
    Panel("Weekly training time (min)", frozenset({"duration_min"}),
          lambda w, r, c: _weekly_bars(w, "duration_min", "Time (min)", c, ".0f")),
    Panel("Weekly calories (kcal)", frozenset({"calories"}),
          lambda w, r, c: _weekly_bars(w, "calories", "Calories (kcal)", c, ".0f")),
    Panel("Average heart rate per workout (bpm)", frozenset({"avg_hr"}),
          lambda w, r, c: _per_workout_line(r, "avg_hr", "Avg HR (bpm)", c)),
    Panel("Weekly elevation gain (m)", frozenset({"elevation_gain_m"}),
          lambda w, r, c: _weekly_bars(w, "elevation_gain_m", "Elevation gain (m)", c, ".0f")),
    Panel("Cadence per workout (spm)", frozenset({"cadence_spm"}),
          lambda w, r, c: _per_workout_line(r, "cadence_spm", "Cadence (spm)", c)),
)


def _placeholder(key: str, title: str, missing: set[str]) -> None:
    names = " and ".join(FIELDS[f].label.lower() for f in sorted(missing, key=COLUMNS.index))
    with st.container(border=True, key=f"panel-ph-{key}"):
        st.markdown(f"**{title}**  \nNo {names} data in this file")


# --- Page ----------------------------------------------------------------------


def render(rows: list[workouts.Workout]) -> None:
    # --- Filter: one row above everything it affects ------------------------
    first, last = rows[0]["date"], rows[-1]["date"]
    if first < last:
        start, end = st.slider(
            "Period", min_value=first, max_value=last, value=(first, last), format="D MMM YYYY"
        )
        rows = [r for r in rows if start <= r["date"] <= end]
    if not rows:
        st.info("No workouts in this period.")
        return

    have = workouts.available_fields(rows)
    summary = workouts.summarize(rows)
    weeks = workouts.weekly(rows)

    # --- Headline numbers (unavailable ones are shown faded with "–") --------
    tiles = [
        ("Workouts", str(summary["workouts"]), None, None),
        ("Per week", f"{summary['workouts_per_week']:.1f}", None, "Workouts per week"),
        ("Distance", f"{summary.get('total_distance_km', 0):.1f} km", "distance_km", None),
        ("Time", _fmt_duration(summary.get("total_duration_min", 0)), "duration_min", None),
        ("Avg pace", summary.get("average_pace"), "pace_min_per_km", "Total time ÷ total distance"),
        ("Longest", f"{summary['longest_workout']['distance_km']:.1f} km" if "longest_workout" in summary else None,
         "distance_km", f"on {summary['longest_workout']['date']}" if "longest_workout" in summary else None),
        ("Calories", f"{summary.get('total_calories', 0):,} kcal", "calories", None),
        ("Avg HR", f"{summary.get('average_heart_rate_bpm')} bpm", "avg_hr", None),
    ]
    cols = st.columns(4)
    for i, (label, value, needs, help_text) in enumerate(tiles):
        if needs is None or needs in have:
            cols[i % 4].metric(label, value or "–", help=help_text)
        else:
            cols[i % 4].metric(label, "–", help=f"No {FIELDS[needs].label.lower()} data in this file")

    jumps = [w for w in weeks if w["volume_jump_warning"]]
    if jumps:
        listed = ", ".join(f"{w['week']} (+{w['volume_change_pct']:.0f}%)" for w in jumps)
        st.warning(
            f"⚠️ Weekly distance rose more than {workouts.VOLUME_JUMP_WARN_PCT:.0f}% in: {listed}. "
            "Big jumps in volume raise injury risk."
        )

    # --- Data frames for charts --------------------------------------------
    color = _series_color()
    wdf = pd.DataFrame(weeks)
    wdf["week_start"] = pd.to_datetime(wdf["week_start"])
    wdf["change"] = wdf["volume_change_pct"].map(lambda v: "–" if pd.isna(v) else f"{v:+.0f}%")
    wdf["status"] = wdf["volume_jump_warning"].map(lambda w: _JUMP if w else "OK")

    rdf = pd.DataFrame(rows)
    rdf["date"] = pd.to_datetime(rdf["date"])
    rdf["pace"] = rdf["pace_min_per_km"].map(workouts.fmt_pace)

    # --- Panels: charts for what the file has, placeholders for the rest -----
    shown = [p for p in PANELS if p.needs <= have]
    hidden = [p for p in PANELS if not p.needs <= have]

    _inject_panel_css()
    for i in range(0, len(shown), 2):
        pair = st.columns(2, gap="medium")
        for j, (col, panel) in enumerate(zip(pair, shown[i:i + 2])):
            with col, st.container(border=True, key=f"panel-{i + j}"):
                st.markdown(f"**{panel.title}**")
                st.altair_chart(panel.build(wdf, rdf, color), width="stretch")

    if hidden:
        st.caption("Not in this file")
        cols = st.columns(min(len(hidden), 4), gap="medium")
        for i, panel in enumerate(hidden):
            with cols[i % len(cols)]:
                _placeholder(str(i), panel.title, set(panel.needs) - have)

    # --- Table views (only columns with data) --------------------------------
    with st.expander("Weekly table"):
        week_cols = ["week", "workouts"] + [c for c, need in [
            ("distance_km", "distance_km"), ("duration_min", "duration_min"),
            ("average_pace", "pace_min_per_km"), ("long_run_km", "distance_km"),
            ("calories", "calories"), ("average_heart_rate_bpm", "avg_hr"),
            ("elevation_gain_m", "elevation_gain_m"), ("change", "distance_km"),
        ] if need in have]
        st.dataframe(wdf[week_cols], hide_index=True, width="stretch")
    with st.expander("All workouts"):
        cols = [c for c in COLUMNS if c in have and c != "pace_min_per_km"]
        if "pace_min_per_km" in have:
            cols.insert(cols.index("duration_min") + 1 if "duration_min" in cols else len(cols), "pace")
        st.dataframe(
            rdf[cols].sort_values("date", ascending=False),
            hide_index=True,
            width="stretch",
            column_config={"date": st.column_config.DateColumn(format="YYYY-MM-DD")},
        )


def template_csv() -> str:
    """The app template with one example row, for users who want to start from it."""
    example = {
        "date": date.today(), "activity": "run", "distance_km": 5.0, "duration_min": 30.0,
        "pace_min_per_km": 6.0, "calories": 350, "avg_hr": 145, "max_hr": 168,
        "elevation_gain_m": 40, "cadence_spm": 172, "notes": "easy run",
    }
    return workouts.to_csv([example])
