"""Import: any user file -> app template, via AI mapping (faked here) or built-in rules."""

from datetime import datetime, time
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from sport_coach.ingest import build_mapping, convert, import_file, read_table
from sport_coach.schema import COLUMNS
from sport_coach.workouts import WorkoutDataError, load_workouts

FIXTURES = Path(__file__).parent / "fixtures"


def run(text: str, mapper=None, name: str = "upload.csv"):
    table = read_table(name, text.encode())
    mapping = build_mapping(table, mapper)
    return table, mapping, convert(table, mapping)


# --- Built-in rules ------------------------------------------------------------


def test_users_example_headers():
    text = "Date,Time (Minute),Distance (km),Calories,Session\n2026-09-01,30,5.0,360,Morning\n"
    _, m, conv = run(text)
    assert m.columns == {"date": "Date", "duration_min": "Time (Minute)", "distance_km": "Distance (km)",
                         "calories": "Calories", "notes": "Session"}
    assert m.units["duration_min"] == "min"
    row = conv.rows[0]
    assert (row["distance_km"], row["duration_min"], row["pace_min_per_km"]) == (5.0, 30.0, 6.0)
    assert row["notes"] == "Morning"
    assert conv.derived == ["pace_min_per_km"]


def test_strava_style_export():
    text = (
        "Activity ID,Activity Date,Activity Name,Activity Type,Elapsed Time,Distance,Calories\n"
        '101,"Sep 1, 2026, 7:30:12 AM",Morning Run,Run,1805,5.02,360\n'
        '102,"Sep 3, 2026, 6:10:00 PM",Evening Run,Run,2210,6.2,441\n'
    )
    _, m, conv = run(text)
    assert m.columns["date"] == "Activity Date"
    assert m.columns["activity"] == "Activity Type"
    assert m.columns["notes"] == "Activity Name"
    assert m.units["duration_min"] == "s"
    assert conv.rows[0]["duration_min"] == 30.08
    assert conv.rows[0]["activity"] == "run"


def test_garmin_style_export_with_heart_rate():
    text = (
        "Activity Type,Date,Title,Distance,Calories,Time,Avg HR,Max HR,Avg Pace,Best Pace,Total Ascent\n"
        "Running,2026-09-01 07:30:00,Easy,5.02,\"1,034\",00:29:30,142,165,5:52,5:01,48\n"
    )
    _, m, conv = run(text)
    assert m.columns["avg_hr"] == "Avg HR"
    assert m.columns["max_hr"] == "Max HR"
    assert m.columns["pace_min_per_km"] == "Avg Pace"
    assert m.columns["elevation_gain_m"] == "Total Ascent"
    assert "Best Pace" not in m.columns.values()
    row = conv.rows[0]
    assert (row["duration_min"], row["calories"], row["avg_hr"]) == (29.5, 1034, 142)


def test_miles_feet_and_month_first_dates():
    text = "Workout Date,Miles,Minutes,Elevation (ft)\n09/13/2026,3.1,28,100\n09/15/2026,5,45,0\n"
    _, m, conv = run(text)
    assert (m.units["distance_km"], m.units["elevation_gain_m"], m.date_order) == ("mi", "ft", "month-first")
    assert conv.rows[0]["date"].isoformat() == "2026-09-13"
    assert conv.rows[0]["distance_km"] == pytest.approx(4.989, abs=0.001)
    assert conv.rows[0]["elevation_gain_m"] == 30.5


def test_title_rows_semicolons_decimal_comma():
    text = "Training log 2026;;;\n;;;\nday;dist (km);duration (h:mm:ss);energy\n01.09.2026;5,2;0:30:15;360\n"
    table, _, conv = run(text)
    assert table.header_line == 3
    assert (conv.rows[0]["distance_km"], conv.rows[0]["duration_min"]) == (5.2, 30.25)


def test_typos_in_headers():
    _, m, _ = run("Dat,Distnace,Duraton\n2026-09-01,5,30\n")
    assert (m.columns["date"], m.columns["distance_km"], m.columns["duration_min"]) == ("Dat", "Distnace", "Duraton")


def test_duration_derived_from_pace():
    _, _, conv = run("date,distance,pace\n2026-09-01,10,5:30\n")
    assert conv.rows[0]["duration_min"] == 55.0
    assert conv.derived == ["duration_min"]


def test_partial_data_is_fine_date_plus_one_measure():
    _, m, conv = run("Date,Calories\n2026-09-01,350\n2026-09-02,410\n")
    assert m.problems() == []
    assert [r["calories"] for r in conv.rows] == [350, 410]
    assert all(r["distance_km"] is None for r in conv.rows)


def test_bad_rows_and_cells():
    text = "date,distance_km,duration_min\n2026-09-01,5,30\nTotal,11,66\n2026-09-03,x,30\n2026-09-04,,\n"
    _, _, conv = run(text)
    assert [r["date"].isoformat() for r in conv.rows] == ["2026-09-01", "2026-09-03"]
    assert conv.rows[1]["distance_km"] is None  # unreadable cell left empty, row kept
    assert conv.ignored_cells == 1
    assert conv.skipped == [(3, "unrecognised date “Total”"), (5, "no measurements")]


@pytest.mark.parametrize("text, msg", [
    ("Distance,Duration\n5,30\n", "no date column"),
    ("Date,Comment\n2026-09-01,nice\n", "no measurement"),
])
def test_unusable_files_explain_why(text, msg):
    with pytest.raises(WorkoutDataError, match=msg):
        run(text)


# --- AI mapper (faked) ----------------------------------------------------------

GERMAN = "Datum,Laufzeit,Strecke,Puls\n01.09.2026,0:30:00,5.0,145\n02.09.2026,0:45:00,7.5,150\n"


def test_ai_mapping_handles_any_language():
    def mapper(headers, samples):
        assert headers == ["Datum", "Laufzeit", "Strecke", "Puls"]
        assert len(samples) == 2 and samples[0][0] == "01.09.2026"
        return {"columns": {"date": "Datum", "duration_min": "Laufzeit", "distance_km": "Strecke",
                            "avg_hr": "Puls"},
                "units": {"distance_km": "km", "duration_min": "clock"}, "date_order": "day-first"}

    _, m, conv = run(GERMAN, mapper)
    assert m.source == "ai"
    assert conv.rows[1]["distance_km"] == 7.5 and conv.rows[1]["avg_hr"] == 150
    assert conv.rows[1]["date"].isoformat() == "2026-09-02"


def test_rules_alone_cannot_map_german():
    _, m = None, build_mapping(read_table("x.csv", GERMAN.encode()))
    assert "distance_km" not in m.columns


def test_ai_answers_are_checked_against_the_data():
    def mapper(headers, samples):
        return {"columns": {"date": "Datum", "distance_km": "Puls",  # wrong? values fit numbers
                            "calories": "Nope",                     # column doesn't exist
                            "activity": "Strecke"},                 # numbers aren't text
                "units": {"distance_km": "parsecs"}}                # invalid unit

    _, m, _ = run(GERMAN, mapper)
    assert "calories" not in m.columns
    assert "activity" not in m.columns
    assert m.units["distance_km"] == "km"  # invalid unit replaced by inference
    assert any("Strecke" in n and "don't fit" in n for n in m.notes)


def test_rules_fill_gaps_left_by_ai():
    _, m, _ = run("Date,Distance,Kcal\n2026-09-01,5,300\n",
                  lambda h, s: {"columns": {"date": "Date", "distance_km": "Distance"}})
    assert m.columns["calories"] == "Kcal"
    assert m.source == "ai+rules"


def test_ai_failure_falls_back_to_rules():
    def broken(headers, samples):
        raise TimeoutError("model timed out")

    _, m, conv = run("Date,Distance,Duration\n2026-09-01,5,30\n", broken)
    assert m.source == "rules"
    assert any("TimeoutError" in n for n in m.notes)
    assert len(conv.rows) == 1


def test_ai_answer_cached_per_header_set(tmp_path):
    calls = []

    def mapper(headers, samples):
        calls.append(headers)
        return {"columns": {"date": "Datum", "distance_km": "Strecke"}}

    cache = tmp_path / "cache.json"
    import_file(tmp_path, "a.csv", GERMAN.encode(), mapper, cache)
    import_file(tmp_path, "b.csv", GERMAN.replace("5.0", "6.0").encode(), mapper, cache)
    assert len(calls) == 1


# --- Pipeline -------------------------------------------------------------------


def test_template_file_is_used_as_is(tmp_path):
    result = import_file(tmp_path, "s.csv", Path("data/workouts/sample_runs.csv").read_bytes(),
                         mapper=lambda h, s: pytest.fail("mapper must not be called"))
    assert result.matched_template and result.count == 14
    assert result.mapping.notes == []
    saved = (tmp_path / "s.csv").read_text().splitlines()[0].split(",")
    assert saved == COLUMNS


def test_mapped_import_reports_and_offers_csv(tmp_path):
    result = import_file(tmp_path, "My Watch.csv", b"Date,Miles,Time\n2026-09-01,3.1,0:28:00\n")
    assert not result.matched_template
    assert result.name == "My_Watch.csv"
    msgs = result.messages()
    assert "Distance ← “Miles” (converted from mi)" in msgs
    assert "Pace — calculated" in msgs
    assert any(m.startswith("Not in your file: Calories") for m in msgs)
    assert result.csv_text == (tmp_path / "My_Watch.csv").read_text()


def test_excel_picks_the_right_sheet_and_handles_native_cells(tmp_path):
    wb = Workbook()
    wb.active.title = "Notes"
    wb.active.append(["My running notes"])
    runs = wb.create_sheet("Runs")
    runs.append(["Exported from my watch"])
    runs.append(["Start", "Distance (mi)", "Moving Time", "Activity"])
    runs.append([datetime(2026, 9, 1, 7, 30), 3.1, time(0, 28, 30), "Run"])
    runs.append([datetime(2026, 9, 2, 7, 30), 5.0, time(0, 46, 0), "Run"])
    buf = BytesIO()
    wb.save(buf)

    result = import_file(tmp_path, "Watch Export.xlsx", buf.getvalue())
    rows = load_workouts(tmp_path, result.name)
    assert (result.name, result.count) == ("Watch_Export.csv", 2)
    assert rows[0]["distance_km"] == pytest.approx(4.989, abs=0.001)
    assert rows[0]["duration_min"] == 28.5


def test_legacy_xls(tmp_path):
    result = import_file(tmp_path, "runs_legacy.xls", (FIXTURES / "runs_legacy.xls").read_bytes())
    assert (result.name, result.count, result.matched_template) == ("runs_legacy.csv", 3, True)


@pytest.mark.parametrize("fname", ["fake.xlsx", "fake.xls"])
def test_corrupt_spreadsheet_rejected(tmp_path, fname):
    with pytest.raises(WorkoutDataError, match="Could not read spreadsheet"):
        import_file(tmp_path, fname, b"not really a spreadsheet")


def test_unsupported_type_rejected(tmp_path):
    with pytest.raises(WorkoutDataError, match="Unsupported file type"):
        import_file(tmp_path, "runs.json", b"{}")


def test_ai_match_survives_a_totals_row_in_a_small_file():
    text = "Datum,Kalorien\n01.09.2026,350\n03.09.2026,520\nSumme,870\n"
    _, m, conv = run(text, lambda h, s: {"columns": {"date": "Datum", "calories": "Kalorien"}})
    assert m.columns["date"] == "Datum"
    assert len(conv.rows) == 2 and conv.skipped == [(4, "unrecognised date “Summe”")]
