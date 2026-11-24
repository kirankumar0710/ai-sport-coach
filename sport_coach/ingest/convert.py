"""Copy a table's data into the template: parse, convert units, derive
pace/duration/distance, skip unusable rows. The LLM never touches values."""

from dataclasses import dataclass, field
from typing import Any

from sport_coach import workouts
from sport_coach.ingest.mapping import UNIT_FACTORS, Mapping
from sport_coach.ingest.parsers import blank, parse_clock, parse_date, parse_number
from sport_coach.ingest.reader import Table
from sport_coach.schema import COLUMNS, FIELDS as TEMPLATE_FIELDS, MEASURES
from sport_coach.workouts import WorkoutDataError


@dataclass
class Conversion:
    rows: list[workouts.Workout]
    skipped: list[tuple[int, str]]   # (row number in the user's file, reason)
    ignored_cells: int = 0           # non-empty cells that couldn't be read
    derived: list[str] = field(default_factory=list)


_ROUND = {"distance_km": 3, "duration_min": 2, "pace_min_per_km": 3, "calories": 0,
          "avg_hr": 0, "max_hr": 0, "elevation_gain_m": 1, "cadence_spm": 0}


def _convert_cell(f: str, raw: Any, m: Mapping) -> float | None:
    kind = TEMPLATE_FIELDS[f].kind
    factor = UNIT_FACTORS.get(f, {}).get(m.units.get(f, ""), 1.0)
    if kind == "duration":
        value = parse_clock(raw, m.duration_two_part == "h:mm")
        if value is not None:
            return value
        n = parse_number(raw)
        return None if n is None else n * factor
    if kind == "pace":
        value = parse_clock(raw)
        if value is None:
            value = parse_number(raw)
        return None if value is None else value * factor
    n = parse_number(raw)
    return None if n is None or n < 0 else n * factor


def convert(table: Table, m: Mapping) -> Conversion:
    if problems := m.problems():
        raise WorkoutDataError("Couldn't import this file: " + "; ".join(problems))
    idx = {f: table.columns.index(col) for f, col in m.columns.items()}
    rows, skipped, ignored, derived = [], [], 0, set()

    for i, cells in enumerate(table.rows):
        line = table.header_line + 1 + i
        if all(blank(v) for v in cells):
            continue
        raw_date = cells[idx["date"]]
        d = parse_date(raw_date, m.date_order)
        if d is None:
            skipped.append((line, f"unrecognised date “{'' if blank(raw_date) else raw_date}”"))
            continue

        row: workouts.Workout = {f: None for f in COLUMNS}
        row["date"] = d
        for f in MEASURES:
            if f in idx and not blank(raw := cells[idx[f]]):
                value = _convert_cell(f, raw, m)
                if value is None:
                    ignored += 1
                row[f] = value

        dist, dur, pace = row["distance_km"], row["duration_min"], row["pace_min_per_km"]
        if pace is None and dist and dur:
            row["pace_min_per_km"] = dur / dist
            derived.add("pace_min_per_km")
        elif dur is None and dist and pace:
            row["duration_min"] = pace * dist
            derived.add("duration_min")
        elif dist is None and dur and pace:
            row["distance_km"] = dur / pace
            derived.add("distance_km")

        if all(row[f] is None for f in MEASURES):
            skipped.append((line, "no measurements"))
            continue

        for f, digits in _ROUND.items():
            if row[f] is not None:
                row[f] = round(row[f], digits) if digits else round(row[f])
        for f in ("activity", "notes"):
            if f in idx and not blank(v := cells[idx[f]]):
                row[f] = str(v).strip().lower() if f == "activity" else str(v).strip()
        rows.append(row)

    return Conversion(rows, skipped, ignored, sorted(derived, key=COLUMNS.index))
