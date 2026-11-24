import pytest

from sport_coach import workouts
from sport_coach.workouts import WorkoutDataError, parse_workouts, save_upload

GOOD = "date,distance_km,duration_min\n2026-01-05,5,30\n2026-01-01,10,60\n"


def test_parse_sorts_and_computes_pace():
    rows = parse_workouts("﻿" + GOOD)  # Excel BOM tolerated
    assert [str(r["date"]) for r in rows] == ["2026-01-01", "2026-01-05"]
    assert rows[0]["pace_min_per_km"] == 6.0
    assert rows[0]["activity"] == "run"


@pytest.mark.parametrize(
    "text, msg",
    [
        ("date,distance_km\n2026-01-01,5\n", "Missing column"),
        ("date,distance_km,duration_min\n2026-13-01,5,30\n", "Line 2"),
        ("date,distance_km,duration_min\n2026-01-01,five,30\n", "Line 2"),
        ("date,distance_km,duration_min\n", "no workouts"),
    ],
)
def test_parse_rejects_bad_files(text, msg):
    with pytest.raises(WorkoutDataError, match=msg):
        parse_workouts(text)


def test_save_upload_sanitises_name(tmp_path):
    name, count = save_upload(tmp_path, "../../my runs (2026).csv", GOOD.encode())
    assert name == "my_runs_2026.csv"
    assert count == 2
    assert (tmp_path / name).is_file()


def test_save_upload_rejects_invalid_without_writing(tmp_path):
    with pytest.raises(WorkoutDataError):
        save_upload(tmp_path, "bad.csv", b"foo,bar\n1,2\n")
    assert not list(tmp_path.iterdir())


def test_weekly_volume_jump_flag():
    rows = parse_workouts(
        "date,distance_km,duration_min\n2026-01-05,10,60\n2026-01-12,12,72\n2026-01-19,12.5,75\n"
    )
    weeks = workouts.weekly(rows)
    assert [w["volume_jump_warning"] for w in weeks] == [False, True, False]
    assert weeks[1]["volume_change_pct"] == 20.0
