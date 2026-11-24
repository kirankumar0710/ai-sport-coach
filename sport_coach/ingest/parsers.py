"""Cell-level parsers: numbers, durations, dates - and whether a column's
values fit a template field. Pure functions, no knowledge of files or mapping."""

import re
from datetime import date, datetime, time, timedelta
from typing import Any

from sport_coach.schema import FIELDS as TEMPLATE_FIELDS

DATE_ORDERS = ("day-first", "month-first")


def blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and v != v) or (isinstance(v, str) and not v.strip())


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
    if isinstance(v, bool) or blank(v):
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
    if blank(v):
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


def non_empty(values: list[Any], limit: int = 300) -> list[Any]:
    return [v for v in values if not blank(v)][:limit]


def share(values: list[Any], ok) -> float:
    vals = non_empty(values)
    return sum(1 for v in vals if ok(v)) / len(vals) if vals else 0.0


def content_fit(field_name: str, values: list[Any]) -> float:
    """Share of a column's values that fit a template field's type."""
    kind = TEMPLATE_FIELDS[field_name].kind
    if kind == "date":
        return max(share(values, lambda v, o=o: parse_date(v, o) is not None) for o in DATE_ORDERS)
    if kind == "number":
        return share(values, lambda v: (n := parse_number(v)) is not None and n >= 0
                      and not isinstance(v, (datetime, date, time)))
    if kind in ("duration", "pace"):
        return share(values, lambda v: parse_clock(v) is not None
                      or (parse_number(v) is not None and not isinstance(v, (datetime, date))))
    if kind == "text":
        return share(values, lambda v: isinstance(v, str) and parse_number(v) is None)
    return 0.0
