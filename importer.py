"""One-time history importer.

The only component that reads storage outside the plugin's own database, and
it reads it read-only, bounded to a window, and never guesses: if the store's
shape is not what this module recognises, it refuses and says so. "The book
begins at install" is a perfectly good answer.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db, redact

logger = logging.getLogger(__name__)

_TS_COLUMNS = ("ts_utc", "ts", "timestamp", "created_at", "created", "time", "date")
_SESSION_COLUMNS = ("session_id", "session", "conversation_id", "thread_id")
_ROLE_COLUMNS = ("role", "author", "sender", "source")
_CONTENT_COLUMNS = ("content", "text", "body", "message", "summary")
_ID_COLUMNS = ("id", "message_id", "rowid")


def import_window(days: int = 7) -> dict:
    """Backfill the ledger from the active profile's session store."""
    days = max(1, min(int(days), 90))
    store = _state_db()
    if store is None:
        raise FileNotFoundError(
            "no session store found for this profile; the book begins at install"
        )

    uri = f"file:{store.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    except sqlite3.Error as exc:
        raise RuntimeError(f"cannot open {store.name} read-only: {exc}") from exc

    conn.row_factory = sqlite3.Row
    try:
        columns = _columns(conn, "messages")
        if not columns:
            raise RuntimeError(
                f"{store.name} has no messages table; refusing to guess at its shape"
            )

        ts_column = _first(columns, _TS_COLUMNS)
        content_column = _first(columns, _CONTENT_COLUMNS)
        if not ts_column or not content_column:
            raise RuntimeError(
                f"{store.name} does not look like a session store "
                f"(columns: {', '.join(sorted(columns))}); refusing to guess"
            )

        session_column = _first(columns, _SESSION_COLUMNS)
        role_column = _first(columns, _ROLE_COLUMNS)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        since = _cutoff_for(conn, ts_column, cutoff)
        selected = [ts_column, content_column]
        for optional in (session_column, role_column):
            if optional and optional not in selected:
                selected.append(optional)

        query = (
            f"SELECT {', '.join(selected)} FROM messages "
            f"WHERE {ts_column} >= ? ORDER BY {ts_column}"
        )
        rows = conn.execute(query, (since,)).fetchall()
    finally:
        conn.close()

    ledger = db.connect()
    written = 0
    skipped = 0
    for row in rows:
        content = row[content_column]
        if not content:
            skipped += 1
            continue

        summary, kinds = redact.summarize(str(content))
        if not summary:
            skipped += 1
            continue

        ts = _iso(row[ts_column])
        session_id = str(row[session_column]) if session_column else None
        role = str(row[role_column]) if role_column else "message"

        # Only what a person said and what the agent answered. System notes,
        # tool payloads and onboarding scaffolding are not a week's evidence.
        if role.lower() not in {"user", "assistant"}:
            skipped += 1
            continue

        event_id = hashlib.sha1(
            f"import|{session_id}|{ts}|{summary}".encode("utf-8", "replace")
        ).hexdigest()

        inserted = db.insert_event(
            ledger,
            {
                "event_id": event_id,
                "ts_utc": ts,
                "session_id": session_id,
                "turn_id": None,
                "subagent_id": None,
                "kind": "message",
                "actor": _actor(role),
                "tool": None,
                "target": role or None,
                "action": "message",
                "outcome": "ok",
                "exit_code": None,
                "duration_ms": None,
                "cost_usd": None,
                "tokens_in": None,
                "tokens_out": None,
                "summary": summary,
                "error_sig": None,
                "redacted": 1 if kinds else 0,
                "raw_ref": f"import:{store.name}",
            },
        )
        written += int(inserted)

    return {
        "source": str(store),
        "days": days,
        "read": len(rows),
        "written": written,
        "skipped": skipped,
        "already_present": len(rows) - written - skipped,
        "mode": "read-only",
    }


def _state_db() -> Path | None:
    """The active profile's state database, or None when there is not one.

    Resolution is the harness's job, not ours. ``get_hermes_home()`` honours the
    context-local profile override, so a gateway thread serving one profile can
    never read another profile's transcripts. There is deliberately no fallback:
    an earlier version guessed at ``~/.hermes`` and ``%LOCALAPPDATA%``, which in
    a multiplexed gateway means importing the launch profile's history into the
    caller's ledger.
    """
    home = db.active_home()
    if not home:
        return None

    candidate = Path(home) / "state.db"
    return candidate if candidate.is_file() else None


def _cutoff_for(conn: sqlite3.Connection, column: str, cutoff: datetime):
    """The window bound in whatever type the store actually uses.

    Hermes stores ``timestamp`` as a float epoch on this build, and as text on
    others. Comparing a number to an ISO string matches nothing, which used to
    make the importer report an empty week.
    """
    try:
        row = conn.execute(
            f"SELECT typeof({column}), {column} FROM messages "
            f"WHERE {column} IS NOT NULL LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        row = None

    if row is None:
        return cutoff.isoformat()

    kind, sample = row[0], row[1]
    if kind in {"integer", "real"}:
        epoch = cutoff.timestamp()
        try:
            if abs(float(sample)) > 1e11:  # milliseconds
                epoch *= 1000
        except (TypeError, ValueError):
            pass
        return epoch

    return cutoff.isoformat()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row["name"]) for row in rows}


def _first(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _actor(role: str) -> str:
    lowered = role.lower()
    if lowered in {"user", "human", "person"}:
        return "human"
    if lowered in {"assistant", "agent", "model"}:
        return "agent"
    if lowered in {"tool", "function"}:
        return "system"
    return "system"


def _iso(value) -> str:
    text = str(value or "")
    if "T" in text:
        return text
    try:
        numeric = float(text)
    except ValueError:
        return text

    if numeric > 1e11:
        numeric = numeric / 1000.0
    return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat(timespec="seconds")
