"""Built-in header matching: synonyms, close spelling and value checks.

Used without an API key, when the AI mapper fails, and to fill fields the AI
left unmapped. Also scores rows when looking for the header row.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import time, timedelta
from typing import TYPE_CHECKING

from sport_coach.ingest.parsers import content_fit, non_empty, parse_clock, parse_date, share
from sport_coach.schema import COLUMNS

if TYPE_CHECKING:
    from sport_coach.ingest.reader import Table

_MIN_SCORE = 0.6       # weakest header-name match the rules accept
_CONTENT_OK = 0.7      # share of non-empty values that must fit, for name-only matches


@dataclass(frozen=True)
class Rule:
    synonyms: tuple[str, ...]
    exclude: frozenset[str] = frozenset()  # header words that rule a column out


RULES: dict[str, Rule] = {
    "date": Rule(
        ("date", "day", "workout date", "activity date", "start date", "start time", "start",
         "date time", "datetime", "timestamp", "when", "begin time"),
        frozenset({"duration", "moving", "elapsed", "total", "end"}),
    ),
    "activity": Rule(
        ("activity", "activity type", "type", "sport", "workout type", "exercise",
         "discipline", "category"),
        frozenset({"id", "date", "time", "count", "gear", "description", "name", "title"}),
    ),
    "distance_km": Rule(
        ("distance", "distance km", "dist", "total distance", "km", "kms", "kilometers",
         "kilometres", "miles", "mileage", "distance mi", "distance miles", "distance m",
         "meters", "metres"),
        frozenset({"pace", "speed", "per", "elevation", "ascent", "descent", "gain", "loss",
                   "climb", "stride", "cadence", "hr", "heart", "max", "swolf"}),
    ),
    "duration_min": Rule(
        ("duration", "time", "moving time", "elapsed time", "total time", "workout time",
         "activity time", "duration min", "minutes", "mins", "run time", "timer time"),
        frozenset({"pace", "per", "start", "end", "date", "day", "zone", "best", "lap",
                   "avg", "average", "rest", "stopped"}),
    ),
    "pace_min_per_km": Rule(
        ("pace", "avg pace", "average pace", "pace min km", "pace min mi",
         "avg pace min km", "avg pace min mi"),
        frozenset({"max", "best", "fastest", "gap", "grade", "moving"}),
    ),
    "calories": Rule(
        ("calories", "kcal", "cal", "energy", "active calories", "calories burned",
         "calories kcal", "total calories"),
        frozenset({"rate", "per", "bmr", "resting"}),
    ),
    "avg_hr": Rule(
        ("avg hr", "average hr", "avg heart rate", "average heart rate", "heart rate", "hr",
         "avg bpm", "mean hr", "pulse"),
        frozenset({"max", "maximum", "peak", "zone", "resting", "min"}),
    ),
    "max_hr": Rule(
        ("max hr", "max heart rate", "maximum heart rate", "peak hr", "max bpm"),
        frozenset({"avg", "average", "zone", "mean"}),
    ),
    "elevation_gain_m": Rule(
        ("elevation gain", "elev gain", "total ascent", "ascent", "climb", "elevation",
         "total climb", "gain"),
        frozenset({"loss", "descent", "max", "min", "low", "high", "lowest", "highest"}),
    ),
    "cadence_spm": Rule(
        ("cadence", "avg cadence", "average cadence", "run cadence", "steps per minute", "spm"),
        frozenset({"max"}),
    ),
    "notes": Rule(
        ("notes", "note", "title", "name", "session", "description", "comment", "comments",
         "activity name", "workout name"),
        frozenset({"id"}),
    ),
}


def norm(text: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # camelCase -> camel case
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def name_score(header: str, rule: Rule) -> float:
    h = norm(header)
    if not h:
        return 0.0
    tokens = set(h.split())
    if tokens & rule.exclude:
        return 0.0
    best = 0.0
    for syn in rule.synonyms:
        if h == syn:
            return 1.0
        syn_tokens = syn.split()
        if set(syn_tokens) <= tokens:  # "total distance (km)" contains "distance"
            best = max(best, 0.85 if len(syn_tokens) > 1 else 0.8)
        ratio = difflib.SequenceMatcher(None, h, syn).ratio()
        if ratio >= 0.8:  # whole-header typo: "distnace", "duraton"
            best = max(best, 0.9 * ratio)
        if len(syn_tokens) == 1 and len(syn) >= 4:
            for t in tokens:  # typo inside a longer header: "totl distnce"
                if len(t) >= 4 and difflib.SequenceMatcher(None, t, syn).ratio() >= 0.8:
                    best = max(best, 0.7)
    return best


def _rule_candidates(table: Table, exclude_cols: set[str], fields: set[str]) -> dict[str, str]:
    scored = []
    for col in table.columns:
        if col in exclude_cols or not non_empty(table.values(col)):
            continue
        for f in fields:
            score = name_score(col, RULES[f])
            if score >= _MIN_SCORE and content_fit(f, table.values(col)) >= _CONTENT_OK:
                scored.append((score, -COLUMNS.index(f), f, col))
    picked: dict[str, str] = {}
    used: set[str] = set()
    for _, _, f, col in sorted(scored, reverse=True):
        if f not in picked and col not in used:
            picked[f] = col
            used.add(col)
    return picked


def rule_mapping(table: Table, already: dict[str, str] | None = None) -> dict[str, str]:
    """Map columns with the built-in rules, filling only fields/columns not yet taken."""
    already = dict(already or {})
    picked = _rule_candidates(table, set(already.values()), set(COLUMNS) - set(already))
    result = {**already, **picked}
    used = set(result.values())
    free = [c for c in table.columns if c not in used and non_empty(table.values(c))]

    # Content-only fallbacks for oddly named date / clock-duration columns.
    if "date" not in result:
        def date_like(col: str) -> float:  # plain numbers could be steps, ids...
            return share(table.values(col), lambda v: not isinstance(v, (int, float))
                          and parse_date(v) is not None)

        best = max(free, key=date_like, default=None)
        if best and date_like(best) >= 0.9:
            result["date"] = best
            free.remove(best)
    if "duration_min" not in result:
        clocks = [c for c in free if share(table.values(c), lambda v: parse_clock(v) is not None) >= 0.9
                  and share(table.values(c), lambda v: isinstance(v, str) and ":" in v or isinstance(v, (time, timedelta))) >= 0.9]
        if clocks:
            result["duration_min"] = clocks[0]
    return result
