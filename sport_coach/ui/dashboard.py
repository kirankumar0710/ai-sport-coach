"""Workout statistics dashboard (Streamlit + Altair).

All numbers come from sport_coach.workouts - the same functions the agent's
tools use - so the dashboard and the coach never disagree.
"""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from sport_coach import workouts

# Reference palette: one series hue + the reserved status "warning" colour.
_SERIES = {"light": "#2a78d6", "dark": "#3987e5"}
_WARNING = "#fab219"


def _series_color() -> str:
    try:
        return _SERIES.get(st.context.theme.type or "light", _SERIES["light"])
    except AttributeError:  # older Streamlit without st.context.theme
        return _SERIES["light"]


def _fmt_duration(minutes: float) -> str:
    h, m = divmod(round(minutes), 60)
    return f"{h}h {m:02d}m"


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

    summary = workouts.summarize(rows)
    weeks = workouts.weekly(rows)

    # --- Headline numbers ---------------------------------------------------
    k = st.columns(6)
    k[0].metric("Workouts", summary["workouts"])
    k[1].metric("Distance", f"{summary['total_distance_km']:.1f} km")
    k[2].metric("Time", _fmt_duration(summary["total_duration_min"]))
    k[3].metric("Avg pace", summary["average_pace"] or "–", help="Total time ÷ total distance")
    k[4].metric("Per week", f"{summary['workouts_per_week']:.1f}", help="Workouts per week")
    k[5].metric(
        "Longest",
        f"{summary['longest_workout']['distance_km']:.1f} km",
        help=f"on {summary['longest_workout']['date']}",
    )

    jumps = [w for w in weeks if w["volume_jump_warning"]]
    if jumps:
        listed = ", ".join(f"{w['week']} (+{w['volume_change_pct']:.0f}%)" for w in jumps)
        st.warning(
            f"⚠️ Weekly distance rose more than {workouts.VOLUME_JUMP_WARN_PCT:.0f}% in: {listed}. "
            "Big jumps in volume raise injury risk.",
        )

    # --- Data frames for charts --------------------------------------------
    color = _series_color()
    wdf = pd.DataFrame(weeks)
    wdf["week_start"] = pd.to_datetime(wdf["week_start"])
    wdf["change"] = wdf["volume_change_pct"].map(
        lambda v: "–" if pd.isna(v) else f"{v:+.0f}%"
    )
    wdf["status"] = wdf["volume_jump_warning"].map(
        lambda w: f">{workouts.VOLUME_JUMP_WARN_PCT:.0f}% jump" if w else "OK"
    )

    rdf = pd.DataFrame(rows)
    rdf["date"] = pd.to_datetime(rdf["date"])
    rdf["pace"] = rdf["pace_min_per_km"].map(workouts.fmt_pace)

    week_x = alt.X("week_start:T", title=None, axis=alt.Axis(format="%d %b", grid=False))
    week_tip = [
        alt.Tooltip("week:N", title="Week"),
        alt.Tooltip("distance_km:Q", title="Distance (km)", format=".1f"),
        alt.Tooltip("workouts:Q", title="Workouts"),
        alt.Tooltip("average_pace:N", title="Avg pace"),
        alt.Tooltip("long_run_km:Q", title="Long run (km)", format=".1f"),
        alt.Tooltip("change:N", title="vs previous week"),
    ]

    left, right = st.columns(2)

    with left:
        st.markdown("**Weekly distance (km)**")
        bars = (
            alt.Chart(wdf)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=18)
            .encode(
                x=week_x,
                y=alt.Y("distance_km:Q", title=None),
                color=alt.Color(
                    "status:N",
                    scale=alt.Scale(
                        domain=["OK", f">{workouts.VOLUME_JUMP_WARN_PCT:.0f}% jump"],
                        range=[color, _WARNING],
                    ),
                    legend=alt.Legend(title=None, orient="top"),
                ),
                tooltip=week_tip,
            )
        )
        labels = (
            alt.Chart(wdf[wdf["volume_jump_warning"]])
            .mark_text(dy=-8, fontSize=11)
            .encode(x=week_x, y="distance_km:Q", text=alt.Text("change:N"))
        )
        st.altair_chart(bars + labels, width="stretch")

    with right:
        st.markdown("**Pace per run (min/km, faster ↑)**")
        pace = (
            alt.Chart(rdf)
            .mark_line(point=alt.OverlayMarkDef(size=64, filled=True), strokeWidth=2, color=color)
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b", grid=False)),
                y=alt.Y(
                    "pace_min_per_km:Q",
                    title=None,
                    scale=alt.Scale(reverse=True, zero=False),
                ),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%a %d %b %Y"),
                    alt.Tooltip("pace:N", title="Pace"),
                    alt.Tooltip("distance_km:Q", title="Distance (km)", format=".1f"),
                    alt.Tooltip("duration_min:Q", title="Duration (min)", format=".1f"),
                ],
            )
        )
        st.altair_chart(pace, width="stretch")

    left, right = st.columns(2)

    with left:
        st.markdown("**Long run per week (km)**")
        long_run = (
            alt.Chart(wdf)
            .mark_line(point=alt.OverlayMarkDef(size=64, filled=True), strokeWidth=2, color=color)
            .encode(x=week_x, y=alt.Y("long_run_km:Q", title=None), tooltip=week_tip)
        )
        st.altair_chart(long_run, width="stretch")

    with right:
        st.markdown("**Workouts per week**")
        freq = (
            alt.Chart(wdf)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=18, color=color)
            .encode(
                x=week_x,
                y=alt.Y("workouts:Q", title=None, axis=alt.Axis(tickMinStep=1)),
                tooltip=week_tip,
            )
        )
        st.altair_chart(freq, width="stretch")

    # --- Table views --------------------------------------------------------
    with st.expander("Weekly table"):
        st.dataframe(
            wdf[["week", "workouts", "distance_km", "average_pace", "long_run_km", "change"]],
            hide_index=True,
            width="stretch",
        )
    with st.expander("All workouts"):
        cols = ["date", "activity", "distance_km", "duration_min", "pace", "calories"]
        st.dataframe(
            rdf[cols].sort_values("date", ascending=False),
            hide_index=True,
            width="stretch",
            column_config={"date": st.column_config.DateColumn(format="YYYY-MM-DD")},
        )


def sample_csv() -> str:
    """Template users can download to see the expected format."""
    return (
        "date,activity,distance_km,duration_min,calories\n"
        f"{date.today().isoformat()},run,5.0,30.0,350\n"
    )
