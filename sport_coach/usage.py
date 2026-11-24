"""LLM usage log: one row per model call, stored in SQLite for the Admin tab.

Rows hold counts, timings and cost only (provider, model, agent, tokens,
latency, status, cost at the time of the call and where its price came from).
No prompts, replies or workout data are stored.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,   -- UTC, ISO 8601
    provider        TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    agent           TEXT    NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,   -- includes thinking tokens
    cached_tokens   INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL,   -- ok | error
    error           TEXT,
    cost_usd        REAL,               -- calculated at call time; NULL if no price known
    price_source    TEXT                -- e.g. "LiteLLM price list (gemini/...)"
);
CREATE INDEX IF NOT EXISTS llm_calls_ts ON llm_calls (ts);
"""


@dataclass(frozen=True)
class UsageRecord:
    ts: datetime
    provider: str
    model: str
    agent: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0
    status: str = "ok"
    error: str | None = None
    cost_usd: float | None = None      # at the price in effect when the call happened
    price_source: str | None = None


# Columns added after the first release; created on older databases at startup.
_ADDED_COLUMNS = {"cost_usd": "REAL", "price_source": "TEXT"}


def now() -> datetime:
    return datetime.now(timezone.utc)


class UsageStore:
    """Thread-safe enough for this app: every operation opens its own connection
    (writes come from the agent's background loop, reads from Streamlit)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript(_SCHEMA)
            existing = {row[1] for row in db.execute("PRAGMA table_info(llm_calls)")}
            for col, sql_type in _ADDED_COLUMNS.items():
                if col not in existing:
                    db.execute(f"ALTER TABLE llm_calls ADD COLUMN {col} {sql_type}")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def add(self, rec: UsageRecord) -> None:
        row = asdict(rec)
        row["ts"] = rec.ts.astimezone(timezone.utc).isoformat()
        cols = ", ".join(row)
        with closing(self._connect()) as db, db:
            db.execute(f"INSERT INTO llm_calls ({cols}) VALUES ({', '.join('?' * len(row))})",
                       tuple(row.values()))

    def records(self, since: datetime | None = None) -> list[UsageRecord]:
        names = [f.name for f in fields(UsageRecord)]
        sql = f"SELECT {', '.join(names)} FROM llm_calls"
        args: tuple = ()
        if since is not None:
            sql += " WHERE ts >= ?"
            args = (since.astimezone(timezone.utc).isoformat(),)
        with closing(self._connect()) as db:
            rows = db.execute(sql + " ORDER BY ts", args).fetchall()
        return [UsageRecord(**{**dict(zip(names, r)), "ts": datetime.fromisoformat(r[0])}) for r in rows]

    def clear(self) -> int:
        with closing(self._connect()) as db, db:
            return db.execute("DELETE FROM llm_calls").rowcount
