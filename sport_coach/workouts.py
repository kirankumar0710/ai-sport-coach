"""Workout data: parsing, validation, storage and deterministic statistics.

Shared by the agent tools and the dashboard, so the numbers the coach quotes
and the numbers the dashboard shows always come from the same code.
"""

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = {"date", "distance_km", "duration_min"}
OPTIONAL_COLUMNS = {"activity", "calories"}
VOLUME_JUMP_WARN_PCT = 10.0  # common "10% rule" for weekly mileage increases

Workout = dict[str, Any]


class WorkoutDataError(ValueError):
    """The workout file is missing, unsafe, or not in the expected format."""


# --- Parsing ----------------------------------------------------------------


def parse_workouts(text: str) -> list[Workout]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))  # tolerate Excel BOM
    columns = {c.strip() for c in reader.fieldnames or []}
    missing = REQUIRED_COLUMNS - columns
    if missing:
        raise WorkoutDataError(
            f"Missing column(s): {', '.join(sorted(missing))}. "
            f"Expected: {', '.join(sorted(REQUIRED_COLUMNS | OPTIONAL_COLUMNS))}"
        )

    rows: list[Workout] = []
    for line_no, raw in enumerate(reader, start=2):  # line 1 is the header
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        try:
            distance = float(row["distance_km"])
            duration = float(row["duration_min"])
            rows.append(
                {
                    "date": date.fromisoformat(row["date"]),
                    "activity": row.get("activity") or "run",
                    "distance_km": distance,
                    "duration_min": duration,
                    "calories": float(row["calories"]) if row.get("calories") else None,
                    "pace_min_per_km": duration / distance if distance > 0 else None,
                }
            )
        except ValueError as exc:
            raise WorkoutDataError(f"Line {line_no}: {exc}") from None
        if distance < 0 or duration < 0:
            raise WorkoutDataError(f"Line {line_no}: distance and duration must be >= 0")

    if not rows:
        raise WorkoutDataError("File contains no workouts")
    return sorted(rows, key=lambda r: r["date"])


# --- Storage ----------------------------------------------------------------

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def list_files(data_dir: Path) -> list[str]:
    return sorted(p.name for p in data_dir.glob("*.csv"))


def resolve_file(data_dir: Path, file_name: str) -> Path:
    """Resolve a file inside data_dir, refusing paths that escape it."""
    root = data_dir.resolve()
    path = (root / file_name).resolve()
    if root not in path.parents:
        raise WorkoutDataError(f"'{file_name}' is outside the workout data directory")
    if not path.is_file():
        raise WorkoutDataError(f"No workout file named '{file_name}'")
    return path


def load_workouts(data_dir: Path, file_name: str) -> list[Workout]:
    return parse_workouts(resolve_file(data_dir, file_name).read_text(encoding="utf-8"))


UPLOAD_TYPES = ("csv", "xlsx", "xls")
_EXCEL_EPOCH = datetime(1899, 12, 30)  # Excel serial day 0 (1900 date system)


def _excel_date_cell(value: Any) -> str:
    """Normalise an Excel date cell to YYYY-MM-DD; leave anything else as text."""
    if value is None or (isinstance(value, float) and value != value):  # NaN
        return ""
    if isinstance(value, datetime):  # includes pandas.Timestamp
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):  # date stored as a serial number
        return (_EXCEL_EPOCH + timedelta(days=float(value))).date().isoformat()
    return str(value).strip()


def excel_to_csv(content: bytes) -> str:
    """Convert the first sheet of an Excel workbook to CSV text.

    Blank rows are kept (and later skipped by the parser) so that error line
    numbers match the row numbers the user sees in Excel.
    """
    import pandas as pd  # only needed for Excel uploads

    try:  # calamine reads both .xlsx and legacy .xls
        df = pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=object, engine="calamine")
    except Exception as exc:  # corrupt file, wrong format, password-protected...
        raise WorkoutDataError(f"Could not read Excel file: {exc}") from None

    df.columns = [str(c).strip() for c in df.columns]
    if "date" in df.columns:
        df["date"] = df["date"].map(_excel_date_cell)
    return df.to_csv(index=False)


def _upload_to_csv(file_name: str, content: bytes) -> str:
    suffix = Path(file_name).suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return excel_to_csv(content)
    if suffix != ".csv":
        raise WorkoutDataError(f"Unsupported file type '{suffix}'. Use: {', '.join(UPLOAD_TYPES)}")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        raise WorkoutDataError("File is not UTF-8 text") from None


def save_upload(data_dir: Path, file_name: str, content: bytes) -> tuple[str, int]:
    """Validate an uploaded CSV/Excel file and store it as CSV.

    Returns (stored name, workout count). Invalid files are rejected before
    anything is written. Excel workbooks are converted from their first sheet.
    """
    text = _upload_to_csv(file_name, content)
    rows = parse_workouts(text)

    stem = _SAFE_NAME.sub("_", Path(file_name).stem).strip("._") or "workouts"
    name = f"{stem}.csv"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / name).write_text(text, encoding="utf-8")
    return name, len(rows)


# --- Statistics -------------------------------------------------------------


def fmt_pace(min_per_km: float | None) -> str | None:
    if not min_per_km:
        return None
    minutes, seconds = divmod(round(min_per_km * 60), 60)
    return f"{minutes}:{seconds:02d} /km"


def summarize(rows: list[Workout]) -> dict[str, Any]:
    cals = [r["calories"] for r in rows if r["calories"] is not None]
    span_days = (rows[-1]["date"] - rows[0]["date"]).days + 1
    total_km = sum(r["distance_km"] for r in rows)
    total_min = sum(r["duration_min"] for r in rows)
    fastest = min(rows, key=lambda r: r["pace_min_per_km"] or float("inf"))
    longest = max(rows, key=lambda r: r["distance_km"])

    return {
        "workouts": len(rows),
        "first_date": str(rows[0]["date"]),
        "last_date": str(rows[-1]["date"]),
        "total_distance_km": round(total_km, 2),
        "total_duration_min": round(total_min, 1),
        "total_calories": round(sum(cals)) if cals else None,
        "average_distance_km": round(total_km / len(rows), 2),
        # distance-weighted: total time / total distance
        "average_pace": fmt_pace(total_min / total_km) if total_km else None,
        "average_pace_min_per_km": round(total_min / total_km, 3) if total_km else None,
        "workouts_per_week": round(len(rows) / max(span_days / 7, 1), 2),
        "fastest_workout": {
            "date": str(fastest["date"]),
            "pace": fmt_pace(fastest["pace_min_per_km"]),
            "distance_km": fastest["distance_km"],
        },
        "longest_workout": {"date": str(longest["date"]), "distance_km": longest["distance_km"]},
    }


def weekly(rows: list[Workout]) -> list[dict[str, Any]]:
    weeks: dict[str, list[Workout]] = defaultdict(list)
    for r in rows:
        year, week, _ = r["date"].isocalendar()
        weeks[f"{year}-W{week:02d}"].append(r)

    out, prev_km = [], None
    for key in sorted(weeks):
        ws = weeks[key]
        km = sum(r["distance_km"] for r in ws)
        mins = sum(r["duration_min"] for r in ws)
        change = round((km - prev_km) / prev_km * 100, 1) if prev_km else None
        out.append(
            {
                "week": key,
                "week_start": str(date.fromisocalendar(*map(int, key.replace("-W", " ").split()), 1)),
                "workouts": len(ws),
                "distance_km": round(km, 2),
                "average_pace": fmt_pace(mins / km) if km else None,
                "average_pace_min_per_km": round(mins / km, 3) if km else None,
                "long_run_km": max(r["distance_km"] for r in ws),
                "volume_change_pct": change,
                "volume_jump_warning": change is not None and change > VOLUME_JUMP_WARN_PCT,
            }
        )
        prev_km = km
    return out
