import pytest

from sport_coach import workouts
from sport_coach.workouts import WorkoutDataError, parse_workouts, save_csv

GOOD = "date,distance_km,duration_min\n2026-01-05,5,30\n2026-01-01,10,60\n"


def test_parse_sorts_and_derives_pace():
    rows = parse_workouts("﻿" + GOOD)  # Excel BOM tolerated
    assert [str(r["date"]) for r in rows] == ["2026-01-01", "2026-01-05"]
    assert rows[0]["pace_min_per_km"] == 6.0
    assert rows[0]["calories"] is None and rows[0]["activity"] is None


@pytest.mark.parametrize(
    "text, msg",
    [
        ("distance_km\n5\n", "'date' column"),
        ("date,notes\n2026-01-01,hi\n", "No measurement columns"),
        ("date,distance_km\n2026-13-01,5\n", "Line 2"),
        ("date,distance_km\n2026-01-01,five\n", "Line 2"),
        ("date,distance_km\n2026-01-01,-1\n", "Line 2"),
        ("date,distance_km\n", "no workouts"),
    ],
)
def test_parse_rejects_bad_files(text, msg):
    with pytest.raises(WorkoutDataError, match=msg):
        parse_workouts(text)


def test_save_csv_sanitises_name(tmp_path):
    name, count = save_csv(tmp_path, "../../my runs (2026).xlsx", GOOD)
    assert (name, count) == ("my_runs_2026.csv", 2)
    assert (tmp_path / name).is_file()


def test_save_csv_rejects_invalid_without_writing(tmp_path):
    with pytest.raises(WorkoutDataError):
        save_csv(tmp_path, "bad.csv", "foo,bar\n1,2\n")
    assert not list(tmp_path.iterdir())


def test_csv_round_trip_keeps_template_columns():
    rows = parse_workouts("date,calories,avg_hr\n2026-01-01,300,140\n")
    text = workouts.to_csv(rows)
    assert text.splitlines()[0] == ",".join(workouts.COLUMNS)
    assert parse_workouts(text)[0]["avg_hr"] == 140


def test_summary_only_reports_available_metrics():
    rows = parse_workouts("date,calories,avg_hr\n2026-01-01,300,140\n2026-01-03,500,150\n")
    s = workouts.summarize(rows)
    assert s["total_calories"] == 800 and s["average_heart_rate_bpm"] == 145
    assert "total_distance_km" not in s and "average_pace" not in s
    assert "Distance" in s["not_available"] and "Calories" not in s["not_available"]
    assert workouts.available_fields(rows) == {"date", "calories", "avg_hr"}


def test_pace_only_file_still_has_average_pace():
    rows = parse_workouts("date,pace_min_per_km\n2026-01-01,5.5\n2026-01-02,6.5\n")
    assert workouts.summarize(rows)["average_pace"] == "6:00 /km"


def test_weekly_volume_jump_flag_and_missing_values():
    rows = parse_workouts(
        "date,distance_km,duration_min\n2026-01-05,10,60\n2026-01-12,12,72\n2026-01-19,12.5,75\n"
    )
    weeks = workouts.weekly(rows)
    assert [w["volume_jump_warning"] for w in weeks] == [False, True, False]
    assert weeks[1]["volume_change_pct"] == 20.0
    assert weeks[0]["calories"] is None and weeks[0]["average_heart_rate_bpm"] is None


def test_weekly_without_distance_has_no_volume_change():
    weeks = workouts.weekly(parse_workouts("date,calories\n2026-01-05,300\n2026-01-12,900\n"))
    assert all(w["distance_km"] is None and w["volume_change_pct"] is None for w in weeks)
