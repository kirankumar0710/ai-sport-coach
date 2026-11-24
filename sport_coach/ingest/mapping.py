"""Decide which user column fills each template field, and in what unit.

Order: our own template as-is -> AI mapper (validated against the values,
cached per header set) -> built-in rules fill the gaps -> unit inference.
"""

import hashlib
import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sport_coach.ingest.parsers import (
    DATE_ORDERS, content_fit, non_empty, parse_clock, parse_date, parse_number, share,
)
from sport_coach.ingest.reader import Table
from sport_coach.ingest.rules import norm, rule_mapping
from sport_coach.schema import COLUMNS, FIELDS as TEMPLATE_FIELDS, MEASURES

# Conversion factors from a source unit to the template unit.
UNIT_FACTORS: dict[str, dict[str, float]] = {
    "distance_km": {"km": 1.0, "mi": 1.609344, "m": 0.001},
    "duration_min": {"min": 1.0, "s": 1 / 60, "h": 60.0, "clock": 1.0},
    "pace_min_per_km": {"min/km": 1.0, "min/mi": 1 / 1.609344},
    "elevation_gain_m": {"m": 1.0, "ft": 0.3048},
}

_AI_CONTENT_OK = 0.5   # AI matches already carry meaning; a majority of fitting values suffices
                       # (small files with a "Total" row would otherwise fail)

# (headers, sample_rows) -> {"columns": {field: header}, "units": {field: unit}, "date_order": str}
HeaderMapper = Callable[[list[str], list[list[str]]], dict[str, Any]]


@dataclass
class Mapping:
    columns: dict[str, str]                       # template field -> user column
    units: dict[str, str] = field(default_factory=dict)  # template field -> source unit
    date_order: str = "day-first"
    duration_two_part: str = "mm:ss"              # how to read "1:30": mm:ss or h:mm
    source: str = "rules"                         # template | ai | rules | ai+rules
    notes: list[str] = field(default_factory=list)

    def problems(self) -> list[str]:
        """Why this mapping can't produce workouts (empty when it can)."""
        out = []
        if "date" not in self.columns:
            out.append("no date column was found")
        if not set(self.columns) & set(MEASURES):
            out.append("no measurement columns (distance, duration, pace, calories, heart rate, ...) were found")
        return out

    def describe(self) -> list[str]:
        """Human-readable lines: 'Distance ← “Strecke” (converted from mi)'."""
        lines = []
        for f in COLUMNS:
            if f in self.columns:
                unit = self.units.get(f)
                conv = f" (converted from {unit})" if unit and unit not in (TEMPLATE_FIELDS[f].unit, "clock") else ""
                lines.append(f"{TEMPLATE_FIELDS[f].label} ← “{self.columns[f]}”{conv}")
        return lines


def is_template(table: Table) -> bool:
    """True when the headers already are our template columns."""
    cols = {c.strip() for c in table.columns if not c.startswith("Column ")}
    return "date" in cols and cols <= set(COLUMNS)


def _validate_ai(table: Table, proposal: dict[str, Any], notes: list[str]) -> tuple[dict[str, str], dict[str, str], str | None]:
    """Keep only AI matches that name a real column and whose values fit the field."""
    columns: dict[str, str] = {}
    units: dict[str, str] = {}
    used: set[str] = set()
    for f, col in (proposal.get("columns") or {}).items():
        if f not in TEMPLATE_FIELDS or not col or col not in table.columns or col in used:
            continue
        if content_fit(f, table.values(col)) < _AI_CONTENT_OK:
            notes.append(f"AI matched “{col}” to {TEMPLATE_FIELDS[f].label}, but its values don't fit, so it was ignored.")
            continue
        columns[f] = col
        used.add(col)
    for f, unit in (proposal.get("units") or {}).items():
        if f in columns and unit in UNIT_FACTORS.get(f, {}):
            units[f] = unit
    order = proposal.get("date_order")
    return columns, units, order if order in DATE_ORDERS else None


def _cache_key(table: Table) -> str:
    return hashlib.sha256(json.dumps(sorted(norm(c) for c in table.columns)).encode()).hexdigest()[:16]


def _ai_proposal(table: Table, mapper: HeaderMapper, cache_path: Path | None) -> dict[str, Any]:
    """Ask the LLM mapper, reusing a cached answer for the same set of headers."""
    key = _cache_key(table)
    cache: dict[str, Any] = {}
    if cache_path and cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            cache = {}
    if key in cache:
        return cache[key]
    proposal = mapper(table.columns, table.sample())
    if cache_path:
        cache[key] = proposal
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2))
    return proposal


def build_mapping(table: Table, mapper: HeaderMapper | None = None, cache_path: Path | None = None) -> Mapping:
    if is_template(table):
        cols = {c.strip(): c for c in table.columns if c.strip() in COLUMNS}
        m = Mapping(columns=cols, source="template")
        _infer_units(table, m)
        return m

    notes: list[str] = []
    columns: dict[str, str] = {}
    units: dict[str, str] = {}
    order = None
    source = "rules"
    if mapper is not None:
        try:
            columns, units, order = _validate_ai(table, _ai_proposal(table, mapper, cache_path), notes)
            source = "ai"
        except Exception as exc:  # network, quota, bad JSON... fall back to rules
            notes.append(f"AI mapping unavailable ({type(exc).__name__}); used built-in rules.")

    filled = rule_mapping(table, columns)
    if source == "ai" and len(filled) > len(columns):
        source = "ai+rules"
    m = Mapping(columns=filled, units=units, source=source, notes=notes)
    _infer_units(table, m)
    if order:
        m.date_order = order
    return m


# --- Unit inference -------------------------------------------------------------


def _unit_from_header(header: str, patterns: dict[str, list[str]]) -> str | None:
    h = header.lower()
    for unit, pats in patterns.items():
        if any(re.search(p, h) for p in pats):
            return unit
    return None


def _unit_from_values(values: list[Any], patterns: dict[str, str]) -> str | None:
    texts = [str(v).lower() for v in non_empty(values) if isinstance(v, str)]
    if not texts:
        return None
    for unit, pattern in patterns.items():
        if sum(1 for t in texts if re.search(pattern, t)) / len(texts) >= 0.6:
            return unit
    return None


def _median_number(values: list[Any]) -> float | None:
    nums = [n for v in non_empty(values) if (n := parse_number(v)) is not None and parse_clock(v) is None]
    return statistics.median(nums) if nums else None


def _infer_units(table: Table, m: Mapping) -> None:
    """Fill in units the AI didn't give (or all of them, for rules/template)."""
    c = m.columns

    if (col := c.get("distance_km")) and "distance_km" not in m.units:
        vals = table.values(col)
        unit = _unit_from_header(col, {
            "mi": [r"\bmi\b", r"\bmiles?\b", r"\bmileage\b"],
            "m": [r"\bm\b", r"\bmeters?\b", r"\bmetres?\b"],
            "km": [r"\bkm\b", r"\bkms\b", r"kilomet", r"distance_km"],
        }) or _unit_from_values(vals, {"km": r"\d\s*km\b", "mi": r"\d\s*mi(les?)?\b", "m": r"\d\s*m\b"})
        if unit is None:
            med = _median_number(vals)
            unit = "m" if med is not None and med > 200 else "km"
            if m.source != "template":
                m.notes.append(f"Distance unit not stated; assumed {'metres' if unit == 'm' else 'kilometres'}.")
        m.units["distance_km"] = unit

    if col := c.get("duration_min"):
        vals = table.values(col)
        if re.search(r"h+\s*:\s*mm(?!\s*:)", col.lower()):
            m.duration_two_part = "h:mm"
        if "duration_min" not in m.units:
            unit = _unit_from_header(col, {
                "s": [r"\bs\b", r"\bsecs?\b", r"\bseconds?\b"],
                "h": [r"\bh\b", r"\bhrs?\b", r"\bhours?\b"],
                "min": [r"\bmins?\b", r"\bminutes?\b", r"duration_min"],
            })
            if unit is None and share(vals, lambda v: parse_clock(v) is not None) >= 0.5:
                unit = "clock"
            if unit is None:
                med = _median_number(vals)
                unit = "s" if med is not None and med > 300 else "h" if med is not None and med < 5 else "min"
                if m.source != "template":
                    word = {"s": "seconds", "h": "hours", "min": "minutes"}[unit]
                    m.notes.append(f"Duration unit not stated; assumed {word}.")
            m.units["duration_min"] = unit

    if (col := c.get("pace_min_per_km")) and "pace_min_per_km" not in m.units:
        m.units["pace_min_per_km"] = _unit_from_header(
            col, {"min/mi": [r"/\s*mi", r"\bmi\b", r"per mile", r"\bmile"]}
        ) or _unit_from_values(table.values(col), {"min/mi": r"/\s*mi"}) or "min/km"

    if (col := c.get("elevation_gain_m")) and "elevation_gain_m" not in m.units:
        m.units["elevation_gain_m"] = _unit_from_header(col, {"ft": [r"\bft\b", r"\bfeet\b"]}) or "m"

    if col := c.get("date"):
        vals = non_empty(table.values(col))
        dmy = sum(1 for v in vals if parse_date(v, "day-first"))
        mdy = sum(1 for v in vals if parse_date(v, "month-first"))
        if mdy > dmy:
            m.date_order = "month-first"
        elif dmy == mdy and any(isinstance(v, str) and re.match(r"\d{1,2}[/.-]\d{1,2}[/.-]\d", v) for v in vals):
            m.notes.append("Dates like 03/04/2026 are ambiguous; assumed day-first (3 April).")
