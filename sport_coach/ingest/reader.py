"""Read an uploaded file into a Table: CSV/TSV/TXT (any delimiter or encoding)
or Excel/ODS (the sheet that looks most like a workout log), with the header
row detected below any title rows."""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from sport_coach.ingest.parsers import blank, parse_date, parse_number
from sport_coach.ingest.rules import RULES, name_score
from sport_coach.workouts import WorkoutDataError

UPLOAD_TYPES = ("csv", "tsv", "txt", "xlsx", "xls", "xlsm", "ods")
_EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".ods"}
_HEADER_SCAN_ROWS = 15
SAMPLE_ROWS = 5        # rows shown to the LLM mapper


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
        rows = [r for r in self.rows if any(not blank(v) for v in r)][:n]
        return [["" if blank(v) else _as_text(v) for v in r] for r in rows]


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
        name: [[None if blank(v) else v for v in row] for row in df.itertuples(index=False)]
        for name, df in frames.items()
    }



def _header_score(cells: list[Any]) -> tuple[int, int]:
    """(template fields the row names, text cells in the row) - higher is more header-like.
    The second part finds headers in languages/terms the rules don't know."""
    found = set()
    texts = 0
    for c in cells:
        if isinstance(c, str) and c.strip() and parse_number(c) is None and parse_date(c) is None:
            texts += 1
            for f, rule in RULES.items():
                if name_score(c, rule) >= 0.7:
                    found.add(f)
    return len(found), texts


def _to_table(raw: list[list[Any]], sheet: str | None = None) -> tuple[Table, tuple[int, int]]:
    scan = [(i, r) for i, r in enumerate(raw[:_HEADER_SCAN_ROWS]) if any(not blank(c) for c in r)]
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
        name = str(header[j]).strip() if j < len(header) and not blank(header[j]) else f"Column {j + 1}"
        n = seen.get(name, 0)
        seen[name] = n + 1
        columns.append(name if n == 0 else f"{name} ({n + 1})")

    # blank rows are kept so reported row numbers match the user's file
    rows = [(list(r) + [None] * width)[:width] for r in raw[best_i + 1:]]
    rows = [[None if blank(v) else v for v in r] for r in rows]
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
