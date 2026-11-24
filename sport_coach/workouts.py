"""Workout data: canonical CSV parsing, storage and deterministic statistics.

Stored files follow the app template (sport_coach.schema). Only `date` is
required per row; every measurement column may be empty. Statistics report
only what the data supports, and say what is not available.

Shared by the agent tools and the dashboard, so the numbers the coach quotes
and the numbers the dashboard shows always come from the same code.
"""

import csv
import io
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from sport_coach.schema import COLUMNS, FIELDS, MEASURES, NUMERIC

VOLUME_JUMP_WARN_PCT = 10.0  # common "10% rule" for weekly mileage increases

Workout = dict[str, Any]


class WorkoutDataError(ValueError):
    """The workout file is missing, unsafe, or not in the expected format."""


# --- Parsing ----------------------------------------------------------------


def parse_workouts(text: str) -> list[Workout]:
    """Parse canonical template CSV. Missing columns/cells become None."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))  # tolerate Excel BOM
    columns = {c.strip() for c in reader.fieldnames or []}
    if "date" not in columns:
        raise WorkoutDataError("Missing the 'date' column")
    if not columns & set(MEASURES):
        raise WorkoutDataError(
            f"No measurement columns. Expected at least one of: {', '.join(MEASURES)}"
        )

    rows: list[Workout] = []
    for line_no, raw in enumerate(reader, start=2):  # line 1 is the header
        cells = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(cells.values()):
            continue
        try:
            row: Workout = {"date": date.fromisoformat(cells["date"])}
            for name in NUMERIC:
                value = cells.get(name)
                row[name] = float(value) if value else None
                if row[name] is not None and row[name] < 0:
                    raise ValueError(f"{name} must be >= 0")
        except ValueError as exc:
            raise WorkoutDataError(f"Line {line_no}: {exc}") from None
        for name in ("activity", "notes"):
            row[name] = cells.get(name) or None
        if row["pace_min_per_km"] is None and row["distance_km"] and row["duration_min"]:
            row["pace_min_per_km"] = row["duration_min"] / row["distance_km"]
        rows.append(row)

    if not rows:
        raise WorkoutDataError("File contains no workouts")
    return sorted(rows, key=lambda r: r["date"])


def to_csv(rows: list[Workout]) -> str:
    """Write rows as canonical template CSV (all columns, fixed order)."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: ("" if r.get(k) is None else r[k]) for k in COLUMNS})
    return out.getvalue()


def available_fields(rows: list[Workout]) -> set[str]:
    """Template fields that have at least one value in these workouts."""
    return {"date"} | {f for f in COLUMNS if f != "date" and any(r.get(f) is not None for r in rows)}


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


def safe_name(file_name: str) -> str:
    stem = _SAFE_NAME.sub("_", Path(file_name).stem).strip("._") or "workouts"
    return f"{stem}.csv"


def save_csv(data_dir: Path, file_name: str, text: str) -> tuple[str, int]:
    """Validate canonical CSV text and store it. Returns (stored name, workout count).

    Uploads in any user format are first mapped to canonical CSV by
    sport_coach.ingest; this is the single place files are written.
    """
    rows = parse_workouts(text)
    name = safe_name(file_name)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / name).write_text(text, encoding="utf-8")
    return name, len(rows)


# --- Statistics -------------------------------------------------------------


def fmt_pace(min_per_km: float | None) -> str | None:
    if not min_per_km:
        return None
    minutes, seconds = divmod(round(min_per_km * 60), 60)
    return f"{minutes}:{seconds:02d} /km"


def _values(rows: list[Workout], key: str) -> list[float]:
    return [r[key] for r in rows if r.get(key) is not None]


def _avg_pace(rows: list[Workout]) -> float | None:
    """Distance-weighted (total time / total distance) when possible."""
    both = [r for r in rows if r.get("distance_km") and r.get("duration_min")]
    if both:
        return sum(r["duration_min"] for r in both) / sum(r["distance_km"] for r in both)
    paces = _values(rows, "pace_min_per_km")
    return mean(paces) if paces else None


def summarize(rows: list[Workout]) -> dict[str, Any]:
    have = available_fields(rows)
    span_days = (rows[-1]["date"] - rows[0]["date"]).days + 1
    out: dict[str, Any] = {
        "workouts": len(rows),
        "first_date": str(rows[0]["date"]),
        "last_date": str(rows[-1]["date"]),
        "workouts_per_week": round(len(rows) / max(span_days / 7, 1), 2),
        "available_metrics": [f for f in MEASURES if f in have],
        "not_available": [FIELDS[f].label for f in MEASURES if f not in have],
    }
    if "distance_km" in have:
        dist = _values(rows, "distance_km")
        longest = max((r for r in rows if r.get("distance_km") is not None), key=lambda r: r["distance_km"])
        out["total_distance_km"] = round(sum(dist), 2)
        out["average_distance_km"] = round(mean(dist), 2)
        out["longest_workout"] = {"date": str(longest["date"]), "distance_km": longest["distance_km"]}
    if "duration_min" in have:
        out["total_duration_min"] = round(sum(_values(rows, "duration_min")), 1)
    if (pace := _avg_pace(rows)) is not None:
        fastest = min((r for r in rows if r.get("pace_min_per_km")), key=lambda r: r["pace_min_per_km"])
        out["average_pace"] = fmt_pace(pace)
        out["average_pace_min_per_km"] = round(pace, 3)
        out["fastest_workout"] = {
            "date": str(fastest["date"]),
            "pace": fmt_pace(fastest["pace_min_per_km"]),
            "distance_km": fastest.get("distance_km"),
        }
    if "calories" in have:
        out["total_calories"] = round(sum(_values(rows, "calories")))
    if "avg_hr" in have:
        out["average_heart_rate_bpm"] = round(mean(_values(rows, "avg_hr")))
    if "max_hr" in have:
        out["max_heart_rate_bpm"] = round(max(_values(rows, "max_hr")))
    if "elevation_gain_m" in have:
        out["total_elevation_gain_m"] = round(sum(_values(rows, "elevation_gain_m")))
    if "cadence_spm" in have:
        out["average_cadence_spm"] = round(mean(_values(rows, "cadence_spm")))
    return out


def _sum_or_none(rows: list[Workout], key: str) -> float | None:
    vals = _values(rows, key)
    return round(sum(vals), 2) if vals else None


def weekly(rows: list[Workout]) -> list[dict[str, Any]]:
    """Per ISO week. Keys are always present; values are None without data."""
    weeks: dict[str, list[Workout]] = defaultdict(list)
    for r in rows:
        year, week, _ = r["date"].isocalendar()
        weeks[f"{year}-W{week:02d}"].append(r)

    out, prev_km = [], None
    for key in sorted(weeks):
        ws = weeks[key]
        km = _sum_or_none(ws, "distance_km")
        pace = _avg_pace(ws)
        hrs = _values(ws, "avg_hr")
        dists = _values(ws, "distance_km")
        change = round((km - prev_km) / prev_km * 100, 1) if km is not None and prev_km else None
        out.append(
            {
                "week": key,
                "week_start": str(date.fromisocalendar(*map(int, key.replace("-W", " ").split()), 1)),
                "workouts": len(ws),
                "distance_km": km,
                "duration_min": _sum_or_none(ws, "duration_min"),
                "average_pace": fmt_pace(pace),
                "average_pace_min_per_km": round(pace, 3) if pace else None,
                "long_run_km": max(dists) if dists else None,
                "calories": _sum_or_none(ws, "calories"),
                "average_heart_rate_bpm": round(mean(hrs)) if hrs else None,
                "elevation_gain_m": _sum_or_none(ws, "elevation_gain_m"),
                "volume_change_pct": change,
                "volume_jump_warning": change is not None and change > VOLUME_JUMP_WARN_PCT,
            }
        )
        prev_km = km
    return out
