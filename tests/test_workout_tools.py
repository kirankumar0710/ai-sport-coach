from pathlib import Path

from sport_coach.tools.workout_tools import make_workout_tools

DATA = Path(__file__).resolve().parents[1] / "data" / "workouts"
tools = {t.__name__: t for t in make_workout_tools(DATA)}


def test_tool_names():
    assert set(tools) == {"list_workout_files", "summarize_workouts", "weekly_trends"}


def test_list_files():
    assert "sample_runs.csv" in tools["list_workout_files"]()["files"]


def test_summary():
    s = tools["summarize_workouts"]("sample_runs.csv")
    assert s["status"] == "success"
    assert s["workouts"] == 14
    assert s["total_distance_km"] == 120.8
    assert s["longest_workout"]["distance_km"] == 16.0


def test_weekly_trends():
    weeks = tools["weekly_trends"]("sample_runs.csv")["weeks"]
    assert weeks[0]["volume_change_pct"] is None
    assert any(w["volume_jump_warning"] for w in weeks)


def test_errors_are_returned_as_data():
    assert tools["summarize_workouts"]("../../README.md")["status"] == "error"
    assert tools["summarize_workouts"]("nope.csv")["status"] == "error"
