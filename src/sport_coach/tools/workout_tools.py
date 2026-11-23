"""Deterministic workout analytics exposed to agents as function tools.

The LLM decides *when* to call these; the numbers are always computed in Python.
Tools return plain dicts so every provider can serialise them.
"""


import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

REQUIRED_COLUMNS = {"date", "distance_km", "duration_min"}


def _resolve(data_dir: Path, file_name: str) -> Path:
    """Resolve a file inside data_dir, refusing paths that escape it."""
    root = data_dir.resolve()
    path = (root / file_name).resolve()
    if root not in path.parents:
        raise ValueError(f"'{file_name}' is outside the workout data directory")
    if not path.is_file():
        raise FileNotFoundError(f"No workout file named '{file_name}'")
    return path


def _fmt_pace(min_per_km: float) -> str:
    minutes, seconds = divmod(round(min_per_km * 60), 60)
    return f"{minutes}:{seconds:02d} /km"


def load_workouts(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
        rows = []
        for row in reader:
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
    return sorted(rows, key=lambda r: r["date"])


def list_workout_files(data_dir: Path) -> dict[str, Any]:
    files = sorted(p.name for p in data_dir.glob("*.csv"))
    return {"status": "success", "files": files}


def summarize_workouts(data_dir: Path, file_name: str) -> dict[str, Any]:
    try:
        rows = load_workouts(_resolve(data_dir, file_name))
    except (ValueError, FileNotFoundError) as exc:
        return {"status": "error", "error": str(exc)}
    if not rows:
        return {"status": "error", "error": "File contains no workouts"}

    paces = [r["pace_min_per_km"] for r in rows if r["pace_min_per_km"]]
    cals = [r["calories"] for r in rows if r["calories"] is not None]
    span_days = (rows[-1]["date"] - rows[0]["date"]).days + 1
    fastest = min(rows, key=lambda r: r["pace_min_per_km"] or float("inf"))
    longest = max(rows, key=lambda r: r["distance_km"])

    return {
        "status": "success",
        "workouts": len(rows),
        "period": f"{rows[0]['date']} to {rows[-1]['date']}",
        "total_distance_km": round(sum(r["distance_km"] for r in rows), 2),
        "total_duration_min": round(sum(r["duration_min"] for r in rows), 1),
        "total_calories": round(sum(cals)) if cals else None,
        "average_distance_km": round(mean(r["distance_km"] for r in rows), 2),
        "average_pace": _fmt_pace(mean(paces)) if paces else None,
        "workouts_per_week": round(len(rows) / (span_days / 7), 2),
        "fastest_workout": {"date": str(fastest["date"]), "pace": _fmt_pace(fastest["pace_min_per_km"]),
                            "distance_km": fastest["distance_km"]},
        "longest_workout": {"date": str(longest["date"]), "distance_km": longest["distance_km"]},
    }


def weekly_trends(data_dir: Path, file_name: str) -> dict[str, Any]:
    try:
        rows = load_workouts(_resolve(data_dir, file_name))
    except (ValueError, FileNotFoundError) as exc:
        return {"status": "error", "error": str(exc)}

    weeks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        year, week, _ = r["date"].isocalendar()
        weeks[f"{year}-W{week:02d}"].append(r)

    out = []
    prev_km = None
    for key in sorted(weeks):
        ws = weeks[key]
        km = sum(r["distance_km"] for r in ws)
        mins = sum(r["duration_min"] for r in ws)
        out.append(
            {
                "week": key,
                "workouts": len(ws),
                "distance_km": round(km, 2),
                "average_pace": _fmt_pace(mins / km) if km else None,
                "long_run_km": max(r["distance_km"] for r in ws),
                "volume_change_pct": round((km - prev_km) / prev_km * 100, 1) if prev_km else None,
            }
        )
        prev_km = km
    return {"status": "success", "weeks": out}


def make_workout_tools(data_dir: Path) -> list:
    """Bind tools to a data directory. The closures' signatures and docstrings
    are what ADK turns into the tool schema the model sees."""

    def list_workout_files_tool() -> dict:
        """List the workout CSV files available for analysis."""
        return list_workout_files(data_dir)

    def summarize_workouts_tool(file_name: str) -> dict:
        """Compute overall statistics for a workout CSV file: totals, averages,
        average pace, workouts per week, fastest and longest workouts.

        Args:
            file_name: Name of the CSV file, e.g. "sample_runs.csv".
        """
        return summarize_workouts(data_dir, file_name)

    def weekly_trends_tool(file_name: str) -> dict:
        """Break a workout CSV file down by ISO week: distance, workout count,
        average pace, long run, and week-over-week volume change in percent.

        Args:
            file_name: Name of the CSV file, e.g. "sample_runs.csv".
        """
        return weekly_trends(data_dir, file_name)

    list_workout_files_tool.__name__ = "list_workout_files"
    summarize_workouts_tool.__name__ = "summarize_workouts"
    weekly_trends_tool.__name__ = "weekly_trends"
    return [list_workout_files_tool, summarize_workouts_tool, weekly_trends_tool]
