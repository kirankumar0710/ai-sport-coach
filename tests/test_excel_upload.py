from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from sport_coach.workouts import WorkoutDataError, load_workouts, save_upload

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = ["date", "activity", "distance_km", "duration_min", "calories"]


def _xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_with_real_dates_text_dates_and_serials(tmp_path):
    content = _xlsx(
        [
            [datetime(2026, 9, 1), "run", 5.0, 30.0, 360],  # real Excel date cell
            ["2026-09-03", "run", 6.0, 36.0, None],  # date typed as text, no calories
            [46271, "run", 10, 61, 720],  # date stored as serial number (2026-09-06)
        ]
    )
    name, count = save_upload(tmp_path, "My Runs.xlsx", content)
    assert (name, count) == ("My_Runs.csv", 3)

    rows = load_workouts(tmp_path, name)
    assert [str(r["date"]) for r in rows] == ["2026-09-01", "2026-09-03", "2026-09-06"]
    assert rows[1]["calories"] is None
    assert rows[2]["pace_min_per_km"] == 6.1


def test_xlsx_error_line_matches_excel_row(tmp_path):
    content = _xlsx(
        [
            [datetime(2026, 9, 1), "run", 5, 30, 1],
            [None, None, None, None, None],  # blank row 3 is skipped, not renumbered
            [datetime(2026, 9, 5), "run", "five", 30, 1],  # Excel row 4
        ]
    )
    with pytest.raises(WorkoutDataError, match="Line 4"):
        save_upload(tmp_path, "bad.xlsx", content)
    assert not list(tmp_path.iterdir())


def test_legacy_xls(tmp_path):
    content = (FIXTURES / "runs_legacy.xls").read_bytes()
    name, count = save_upload(tmp_path, "runs_legacy.xls", content)
    assert (name, count) == ("runs_legacy.csv", 3)
    assert str(load_workouts(tmp_path, name)[0]["date"]) == "2026-10-01"


@pytest.mark.parametrize("fname", ["fake.xlsx", "fake.xls"])
def test_corrupt_excel_rejected(tmp_path, fname):
    with pytest.raises(WorkoutDataError, match="Could not read Excel file"):
        save_upload(tmp_path, fname, b"not really a spreadsheet")


def test_unsupported_type_rejected(tmp_path):
    with pytest.raises(WorkoutDataError, match="Unsupported file type"):
        save_upload(tmp_path, "runs.json", b"{}")
