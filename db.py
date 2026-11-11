"""Ledger schema and connection handling.

Every row Imprint keeps lives in the plugin's own SQLite database, opened
through Hermes' sanctioned storage helper so it survives ``hermes plugins
update`` and follows the active profile. Nothing else on disk is written.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

PLUGIN_NAME = "imprint"
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY,
  event_id    TEXT NOT NULL UNIQUE,
  ts_utc      TEXT NOT NULL,
  session_id  TEXT,
  turn_id     TEXT,
  subagent_id TEXT,
  kind        TEXT NOT NULL,
  actor       TEXT NOT NULL,
  tool        TEXT,
  target      TEXT,
  action      TEXT,
  outcome     TEXT,
  exit_code   INTEGER,
  duration_ms INTEGER,
  cost_usd    REAL,
  tokens_in   INTEGER,
  tokens_out  INTEGER,
  summary     TEXT,
  error_sig   TEXT,
  redacted    INTEGER NOT NULL DEFAULT 0,
  raw_ref     TEXT
);
CREATE INDEX IF NOT EXISTS events_ts   ON events(ts_utc);
CREATE INDEX IF NOT EXISTS events_sess ON events(session_id, ts_utc);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind, outcome);

CREATE TABLE IF NOT EXISTS quests (
  id INTEGER PRIMARY KEY, week TEXT, key TEXT, label TEXT,
  first_ts TEXT, last_ts TEXT, stakes REAL, status TEXT
);

CREATE TABLE IF NOT EXISTS chapters (
  id INTEGER PRIMARY KEY, book_id INTEGER, ordinal INTEGER,
  title TEXT, genre TEXT, body_md TEXT, citations_json TEXT,
  verified_ratio REAL, word_count INTEGER
);

CREATE TABLE IF NOT EXISTS books (
  id INTEGER PRIMARY KEY, week TEXT UNIQUE, title TEXT, genre TEXT,
  compiled_at TEXT, pdf_path TEXT, epub_path TEXT, html_path TEXT,
  sentences_total INTEGER, sentences_verified INTEGER
);

CREATE TABLE IF NOT EXISTS bible (
  id INTEGER PRIMARY KEY, kind TEXT,
  name TEXT, first_seen TEXT, notes TEXT, open INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS exclusions (pattern TEXT PRIMARY KEY, added_at TEXT);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def active_home() -> str | None:
    """The profile Hermes is serving right now, or None outside a Hermes process.

    ``hermes_constants.get_hermes_home()`` resolves the context-local override
    first, so a gateway thread serving profile B gets B even when the process
    was launched with profile A's environment. When the harness is not importable
    the answer is None rather than a guess: reading another profile's store is
    worse than importing nothing.
    """
    try:
        from hermes_constants import get_hermes_home
    except Exception:
        logger.warning("imprint: hermes_constants unavailable; profile scope unknown")
        return None

    try:
        return str(get_hermes_home())
    except Exception:
        logger.warning("imprint: could not resolve the active profile", exc_info=True)
        return None


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open the ledger and make sure the schema is in place.

    With no path, the database lives in the plugin data directory Hermes
    hands us. ``IMPRINT_DB_PATH`` exists so tests and a headless compile can
    point at a temporary ledger without Hermes in the process.
    """
    if path is None:
        override = os.environ.get("IMPRINT_DB_PATH")
        if override:
            path = override

    if path is None:
        from plugins.plugin_storage import plugin_db

        conn = plugin_db(PLUGIN_NAME)
    else:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), timeout=30.0)

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def insert_event(conn: sqlite3.Connection, row: dict) -> bool:
    """Insert one event, ignoring a duplicate ``event_id``.

    Returns True when a row was written. Replaying a hook is a no-op, which is
    what keeps a repeated payload from inflating the book.
    """
    columns = (
        "event_id",
        "ts_utc",
        "session_id",
        "turn_id",
        "subagent_id",
        "kind",
        "actor",
        "tool",
        "target",
        "action",
        "outcome",
        "exit_code",
        "duration_ms",
        "cost_usd",
        "tokens_in",
        "tokens_out",
        "summary",
        "error_sig",
        "redacted",
        "raw_ref",
    )
    values = [row.get(column) for column in columns]
    placeholders = ", ".join("?" for _ in columns)
    cursor = conn.execute(
        f"INSERT OR IGNORE INTO events ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return cursor.rowcount > 0


def event_count(conn: sqlite3.Connection, week: str | None = None) -> int:
    if week is None:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM events WHERE ts_utc >= ? AND ts_utc < ?",
        _week_bounds(week),
    ).fetchone()[0]


def _week_bounds(week: str) -> tuple[str, str]:
    """ISO week label (``2026-W45``) to a half-open UTC timestamp range."""
    from datetime import datetime, timedelta, timezone

    year_text, week_text = week.split("-W")
    start = datetime.fromisocalendar(int(year_text), int(week_text), 1)
    start = start.replace(tzinfo=timezone.utc)
    return start.isoformat(), (start + timedelta(days=7)).isoformat()


def week_of(ts_utc: str) -> str:
    """The ISO week label for a stored timestamp."""
    from datetime import datetime

    return datetime.fromisoformat(ts_utc).strftime("%G-W%V")
