"""Import any workout file into the app template (sport_coach.schema).

Users export workouts from many apps and spreadsheets, each with its own
headers, units and date formats. No review step - we map automatically:

  1. read the table (CSV/TSV/TXT with any delimiter, or any Excel/ODS sheet)
     and find the header row (title rows above it are ignored)
  2. if the headers already are our template columns, use them as-is
  3. otherwise map user headers -> template fields:
       - an LLM mapper (headers + a few sample rows -> JSON), when available
       - built-in rules (synonyms, close spelling) as fallback and gap-filler
     every proposed match is checked against the column's actual values
  4. copy the data into the template in Python: convert units, parse dates,
     derive pace/duration/distance where possible
  5. save canonical CSV; rows without a date or any measurement are skipped
     and reported

The LLM only names columns and units. All values are converted here, in
deterministic code, so a model can never invent or alter a number.
"""

import csv
import difflib
import hashlib
import io
import json
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable

from sport_coach import workouts
from sport_coach.schema import COLUMNS, FIELDS as TEMPLATE_FIELDS, MEASURES
from sport_coach.workouts import WorkoutDataError

UPLOAD_TYPES = ("csv", "tsv", "txt", "xlsx", "xls", "xlsm", "ods")
_EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".ods"}

# Conversion factors from a source unit to the template unit.
UNIT_FACTORS: dict[str, dict[str, float]] = {
    "distance_km": {"km": 1.0, "mi": 1.609344, "m": 0.001},
    "duration_min": {"min": 1.0, "s": 1 / 60, "h": 60.0, "clock": 1.0},
    "pace_min_per_km": {"min/km": 1.0, "min/mi": 1 / 1.609344},
    "elevation_gain_m": {"m": 1.0, "ft": 0.3048},
}
DATE_ORDERS = ("day-first", "month-first")

_MIN_SCORE = 0.6       # weakest header-name match the rules accept
_CONTENT_OK = 0.7      # share of non-empty values that must fit, for rule (name-only) matches
_AI_CONTENT_OK = 0.5   # AI matches already carry meaning; a majority of fitting values suffices
                       # (small files with a "Total" row would otherwise fail)
_HEADER_SCAN_ROWS = 15
SAMPLE_ROWS = 5        # rows shown to the LLM mapper

# (headers, sample_rows) -> {"columns": {field: header}, "units": {field: unit}, "date_order": str}
HeaderMapper = Callable[[list[str], list[list[str]]], dict[str, Any]]


# --- Built-in matching rules ------------------------------------------------


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


# --- Reading ------------------------------------------------------------------


@dataclass
class Table:
    columns: list[str]
    rows: list[list[Any]]
    header_line: int            # 1-based row number of the header in the source
    sheet: str | None = None

    def values(self, column: str) -> list[Any]:
        i = self.columns.index(column)
        return [r[i] for r in self.rows]

    def sample(self, n: int = SAMPLE_ROWS) -> list[list[str]]:
        rows = [r for r in self.rows if any(not _blank(v) for v in r)][:n]
        return [["" if _blank(v) else _as_text(v) for v in r] for r in rows]


def _as_text(v: Any) -> str:
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, (date, time)):
        return v.isoformat()
    return str(v)


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")  # never fails


def _read_delimited(content: bytes) -> list[list[Any]]:
    text = _decode(content)
    sample = "\n".join(text.splitlines()[:50])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def _read_sheets(content: bytes) -> dict[str, list[list[Any]]]:
    import pandas as pd  # only needed for spreadsheets

    try:  # calamine reads .xlsx, .xls, .xlsm and .ods
        frames = pd.read_excel(
            io.BytesIO(content), sheet_name=None, header=None, dtype=object, engine="calamine"
        )
    except Exception as exc:  # corrupt, password-protected, not a spreadsheet...
        raise WorkoutDataError(f"Could not read spreadsheet: {exc}") from None
    return {
        name: [[None if _blank(v) else v for v in row] for row in df.itertuples(index=False)]
        for name, df in frames.items()
    }


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip())


def _header_score(cells: list[Any]) -> tuple[int, int]:
    """(template fields the row names, text cells in the row) - higher is more header-like.
    The second part finds headers in languages/terms the rules don't know."""
    found = set()
    texts = 0
    for c in cells:
        if isinstance(c, str) and c.strip() and parse_number(c) is None and parse_date(c) is None:
            texts += 1
            for f, rule in RULES.items():
                if _name_score(c, rule) >= 0.7:
                    found.add(f)
    return len(found), texts


def _to_table(raw: list[list[Any]], sheet: str | None = None) -> tuple[Table, tuple[int, int]]:
    scan = [(i, r) for i, r in enumerate(raw[:_HEADER_SCAN_ROWS]) if any(not _blank(c) for c in r)]
    if not scan:
        raise WorkoutDataError("The file is empty")
    best_i, best_score = scan[0][0], (-1, -1)
    for i, r in scan:
        score = _header_score(r)
        if score > best_score:
            best_i, best_score = i, score

    header = raw[best_i]
    width = max(len(r) for r in raw[best_i:])
    columns, seen = [], {}
    for j in range(width):
        name = str(header[j]).strip() if j < len(header) and not _blank(header[j]) else f"Column {j + 1}"
        n = seen.get(name, 0)
        seen[name] = n + 1
        columns.append(name if n == 0 else f"{name} ({n + 1})")

    # blank rows are kept so reported row numbers match the user's file
    rows = [(list(r) + [None] * width)[:width] for r in raw[best_i + 1:]]
    rows = [[None if _blank(v) else v for v in r] for r in rows]
    return Table(columns, rows, header_line=best_i + 1, sheet=sheet), best_score


def read_table(file_name: str, content: bytes) -> Table:
    suffix = Path(file_name).suffix.lower()
    if suffix in _EXCEL_SUFFIXES:
        candidates = []
        for name, raw in _read_sheets(content).items():
            try:
                candidates.append(_to_table(raw, sheet=name))
            except WorkoutDataError:
                continue
        if not candidates:
            raise WorkoutDataError("The spreadsheet has no data")
        # the sheet whose header looks most like a workout log
        return max(candidates, key=lambda t: (t[1], len(t[0].rows)))[0]
    if suffix in {".csv", ".tsv", ".txt", ""}:
        return _to_table(_read_delimited(content))[0]
    raise WorkoutDataError(f"Unsupported file type '{suffix}'. Use: {', '.join(UPLOAD_TYPES)}")


# --- Value parsers ------------------------------------------------------------

_NUMERIC_TEXT = re.compile(r"\s*[-+]?[\d.,\s]*\d[\d.,]*\s*[a-zA-Z/%]*\.?\s*")  # "5.2 km", "1,234", "350 kcal"
_CLOCK = re.compile(r"^\s*(\d+):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?\s*(?:(?:min)?\s*/\s*\w+)?\s*$")
_HMS_TEXT = re.compile(
    r"^\s*(?:(\d+(?:\.\d+)?)\s*h(?:rs?|ours?)?)?\s*(?:(\d+(?:\.\d+)?)\s*m(?:in(?:s|utes?)?)?)?"
    r"\s*(?:(\d+(?:\.\d+)?)\s*s(?:ec(?:s|onds?)?)?)?\s*$",
    re.IGNORECASE,
)
_TIME_TAIL = re.compile(
    r"[ T,]+\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:[AaPp][Mm])?\s*(?:Z|[+-]\d{2}:?\d{2}|[A-Z]{2,4})?\s*$"
)
_EXCEL_EPOCH = datetime(1899, 12, 30)

_YMD = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d")
_DMY = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y")
_MDY = ("%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y", "%m/%d/%y", "%m-%d-%y")
_TEXT = ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y",
         "%a %d %b %Y", "%a, %d %b %Y", "%a, %b %d, %Y", "%A, %B %d, %Y", "%d-%b-%Y", "%d-%b-%y")


def parse_number(v: Any) -> float | None:
    if isinstance(v, bool) or _blank(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", " ")
    if not _NUMERIC_TEXT.fullmatch(s):  # rejects dates/times like "2026-09-01 07:30"
        return None
    if re.fullmatch(r"[-+]?\d+,\d{1,2}(?:\s*[^\d\s].*)?", s):  # decimal comma: "5,2 km"
        s = s.replace(",", ".", 1)
    m = re.search(r"[-+]?(?:\d[\d,\s]*\.?\d*|\.\d+)", s)
    if not m:
        return None
    try:
        return float(m.group().replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def parse_clock(v: Any, two_part_is_hours: bool = False) -> float | None:
    """Clock-style durations -> minutes: 'h:mm:ss', 'mm:ss' (or 'h:mm' if told), '1h 05m'."""
    if isinstance(v, timedelta):
        return v.total_seconds() / 60
    if isinstance(v, time):
        return v.hour * 60 + v.minute + v.second / 60
    if isinstance(v, datetime) and v.year <= 1900:  # Excel time-only cell
        return v.hour * 60 + v.minute + v.second / 60
    if not isinstance(v, str):
        return None
    m = _CLOCK.match(v)
    if not m:
        t = _HMS_TEXT.match(v)  # "1h 05m 30s", "45 min 10 sec"
        if t and any(t.groups()) and re.search(r"[hHmMsS]", v):
            h, mi, se = (float(x) if x else 0.0 for x in t.groups())
            return h * 60 + mi + se / 60
        return None
    a, b, c = m.group(1), m.group(2), m.group(3)
    if c is not None:
        return int(a) * 60 + int(b) + float(c) / 60
    return int(a) * 60 + int(b) if two_part_is_hours else int(a) + int(b) / 60


def parse_date(v: Any, order: str = "day-first") -> date | None:
    if _blank(v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 <= v <= 80000:  # Excel serial date
            return (_EXCEL_EPOCH + timedelta(days=float(v))).date()
        if 19000101 <= v <= 21001231 and float(v).is_integer():  # 20260901
            v = str(int(v))
        else:
            return None
    s = str(v).strip()
    if re.fullmatch(r"\d{5}(?:\.\d+)?", s):  # serial number stored as text
        return parse_date(float(s), order)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    formats = _YMD + (_DMY if order == "day-first" else _MDY) + _TEXT
    for candidate in (s, _TIME_TAIL.sub("", s).strip().rstrip(",")):
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


# --- Matching helpers -----------------------------------------------------------


def _norm(text: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)  # camelCase -> camel case
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _name_score(header: str, rule: Rule) -> float:
    h = _norm(header)
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


def _non_empty(values: list[Any], limit: int = 300) -> list[Any]:
    return [v for v in values if not _blank(v)][:limit]


def _share(values: list[Any], ok) -> float:
    vals = _non_empty(values)
    return sum(1 for v in vals if ok(v)) / len(vals) if vals else 0.0


def content_fit(field_name: str, values: list[Any]) -> float:
    """Share of a column's values that fit a template field's type."""
    kind = TEMPLATE_FIELDS[field_name].kind
    if kind == "date":
        return max(_share(values, lambda v, o=o: parse_date(v, o) is not None) for o in DATE_ORDERS)
    if kind == "number":
        return _share(values, lambda v: (n := parse_number(v)) is not None and n >= 0
                      and not isinstance(v, (datetime, date, time)))
    if kind in ("duration", "pace"):
        return _share(values, lambda v: parse_clock(v) is not None
                      or (parse_number(v) is not None and not isinstance(v, (datetime, date))))
    if kind == "text":
        return _share(values, lambda v: isinstance(v, str) and parse_number(v) is None)
    return 0.0


# --- Mapping ------------------------------------------------------------------


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


def _rule_candidates(table: Table, exclude_cols: set[str], fields: set[str]) -> dict[str, str]:
    scored = []
    for col in table.columns:
        if col in exclude_cols or not _non_empty(table.values(col)):
            continue
        for f in fields:
            score = _name_score(col, RULES[f])
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
    free = [c for c in table.columns if c not in used and _non_empty(table.values(c))]

    # Content-only fallbacks for oddly named date / clock-duration columns.
    if "date" not in result:
        def date_like(col: str) -> float:  # plain numbers could be steps, ids...
            return _share(table.values(col), lambda v: not isinstance(v, (int, float))
                          and parse_date(v) is not None)

        best = max(free, key=date_like, default=None)
        if best and date_like(best) >= 0.9:
            result["date"] = best
            free.remove(best)
    if "duration_min" not in result:
        clocks = [c for c in free if _share(table.values(c), lambda v: parse_clock(v) is not None) >= 0.9
                  and _share(table.values(c), lambda v: isinstance(v, str) and ":" in v or isinstance(v, (time, timedelta))) >= 0.9]
        if clocks:
            result["duration_min"] = clocks[0]
    return result


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
    return hashlib.sha256(json.dumps(sorted(_norm(c) for c in table.columns)).encode()).hexdigest()[:16]


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
    texts = [str(v).lower() for v in _non_empty(values) if isinstance(v, str)]
    if not texts:
        return None
    for unit, pattern in patterns.items():
        if sum(1 for t in texts if re.search(pattern, t)) / len(texts) >= 0.6:
            return unit
    return None


def _median_number(values: list[Any]) -> float | None:
    nums = [n for v in _non_empty(values) if (n := parse_number(v)) is not None and parse_clock(v) is None]
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
            if unit is None and _share(vals, lambda v: parse_clock(v) is not None) >= 0.5:
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
        vals = _non_empty(table.values(col))
        dmy = sum(1 for v in vals if parse_date(v, "day-first"))
        mdy = sum(1 for v in vals if parse_date(v, "month-first"))
        if mdy > dmy:
            m.date_order = "month-first"
        elif dmy == mdy and any(isinstance(v, str) and re.match(r"\d{1,2}[/.-]\d{1,2}[/.-]\d", v) for v in vals):
            m.notes.append("Dates like 03/04/2026 are ambiguous; assumed day-first (3 April).")


# --- Conversion ---------------------------------------------------------------


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
        if all(_blank(v) for v in cells):
            continue
        raw_date = cells[idx["date"]]
        d = parse_date(raw_date, m.date_order)
        if d is None:
            skipped.append((line, f"unrecognised date “{'' if _blank(raw_date) else raw_date}”"))
            continue

        row: workouts.Workout = {f: None for f in COLUMNS}
        row["date"] = d
        for f in MEASURES:
            if f in idx and not _blank(raw := cells[idx[f]]):
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
            if f in idx and not _blank(v := cells[idx[f]]):
                row[f] = str(v).strip().lower() if f == "activity" else str(v).strip()
        rows.append(row)

    return Conversion(rows, skipped, ignored, sorted(derived, key=COLUMNS.index))


# --- Pipeline -------------------------------------------------------------------


@dataclass
class ImportResult:
    name: str                      # stored file name
    count: int
    matched_template: bool         # False -> the user is told we mapped it
    mapping: Mapping
    conversion: Conversion
    csv_text: str                  # what was saved (offered as a download)

    def messages(self) -> list[str]:
        out = self.mapping.describe()
        for f in self.conversion.derived:
            out.append(f"{TEMPLATE_FIELDS[f].label} — calculated")
        missing = [TEMPLATE_FIELDS[f].label for f in MEASURES
                   if f not in self.mapping.columns and f not in self.conversion.derived]
        if missing:
            out.append("Not in your file: " + ", ".join(missing))
        return out


def import_file(
    data_dir: Path,
    file_name: str,
    content: bytes,
    mapper: HeaderMapper | None = None,
    cache_path: Path | None = None,
) -> ImportResult:
    """Read any workout file, map it onto the template, convert and save it."""
    table = read_table(file_name, content)
    if not any(any(not _blank(v) for v in r) for r in table.rows):
        raise WorkoutDataError("The file has a header but no data rows")
    mapping = build_mapping(table, mapper, cache_path)
    conv = convert(table, mapping)
    if not conv.rows:
        reasons = "; ".join(f"row {ln}: {why}" for ln, why in conv.skipped[:3])
        raise WorkoutDataError(f"No usable workouts found ({reasons})")
    text = workouts.to_csv(conv.rows)
    name, count = workouts.save_csv(data_dir, file_name, text)
    return ImportResult(name, count, mapping.source == "template", mapping, conv, text)
