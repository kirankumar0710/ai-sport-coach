from pathlib import Path

from sport_coach.tools.workout_tools import list_workout_files, summarize_workouts, weekly_trends

DATA = Path(__file__).resolve().parents[1] / "data" / "workouts"


def test_list_files():
    assert "sample_runs.csv" in list_workout_files(DATA)["files"]


def test_summary():
    s = summarize_workouts(DATA, "sample_runs.csv")
    assert s["status"] == "success"
    assert s["workouts"] == 14
    assert s["total_distance_km"] == 120.8
    assert s["longest_workout"]["distance_km"] == 16.0


def test_weekly_trends_volume_change():
    weeks = weekly_trends(DATA, "sample_runs.csv")["weeks"]
    assert weeks[0]["volume_change_pct"] is None
    assert all("distance_km" in w for w in weeks)


def test_path_traversal_rejected():
    assert summarize_workouts(DATA, "../../pyproject.toml")["status"] == "error"


def test_missing_file():
    assert summarize_workouts(DATA, "nope.csv")["status"] == "error"
