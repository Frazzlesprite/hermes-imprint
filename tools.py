"""Tool handlers and the ``/imprint`` command.

Handlers follow Hermes' contract: take ``args``, accept ``**kwargs``, always
return a JSON string, never raise. The command returns plain text because a
person reads it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from . import db, schemas

logger = logging.getLogger(__name__)


def _ok(**payload) -> str:
    return json.dumps({"ok": True, **payload}, ensure_ascii=False)


def _error(message: str, **payload) -> str:
    return json.dumps({"ok": False, "error": message, **payload}, ensure_ascii=False)


def _settings(**kwargs) -> dict:
    settings = kwargs.get("plugin_settings")
    return settings if isinstance(settings, dict) else {}


def _conn():
    from .capture import _conn as capture_conn

    return capture_conn()


def ledger_status(args: dict, **kwargs) -> str:
    """Ledger size, coverage and what is still open."""
    try:
        conn = _conn()
        total = db.event_count(conn)
        row = conn.execute(
            "SELECT MIN(ts_utc) AS first, MAX(ts_utc) AS last FROM events"
        ).fetchone()
        weeks = [
            record[0]
            for record in conn.execute(
                "SELECT DISTINCT substr(ts_utc, 1, 10) FROM events ORDER BY 1"
            ).fetchall()
        ]
        book = conn.execute(
            "SELECT week, title, genre, compiled_at FROM books ORDER BY compiled_at DESC LIMIT 1"
        ).fetchone()
        open_threads = conn.execute(
            "SELECT COUNT(*) FROM quests WHERE status = 'open'"
        ).fetchone()[0]

        week_labels = sorted({_week_label(day) for day in weeks})
        return _ok(
            events=total,
            first_event=row["first"] if row else None,
            last_event=row["last"] if row else None,
            weeks=week_labels,
            open_threads=open_threads,
            last_book=dict(book) if book else None,
        )
    except Exception as exc:
        logger.warning("imprint: status failed", exc_info=True)
        return _error(f"could not read the ledger: {exc}")


def compile_week(args: dict, **kwargs) -> str:
    """Build or rebuild one week's book."""
    try:
        from . import pipeline

        week = (args or {}).get("week") or _current_week()
        genre = (args or {}).get("genre")
        settings = _settings(**kwargs)
        if genre and genre not in {"epic", "noir", "ships-log"}:
            return _error(f"unknown genre {genre!r}; use epic, noir or ships-log")

        result = pipeline.compile_week(
            week,
            genre or settings.get("genre", "epic"),
            llm=kwargs.get("llm"),
            settings=settings,
        )
        return _ok(**result)
    except ImportError as exc:
        return _error(f"imprint is not fully installed: {exc}")
    except Exception as exc:
        logger.warning("imprint: compile failed", exc_info=True)
        return _error(f"compile failed: {exc}")


def preview_book(args: dict, **kwargs) -> str:
    """The executive edition, as text, without rendering anything."""
    try:
        from . import pipeline

        book_id = (args or {}).get("book_id")
        text = pipeline.executive_text(book_id)
        if not text:
            return _error("no compiled book yet; call imprint_compile first")
        return _ok(book_id=book_id, text=text)
    except Exception as exc:
        logger.warning("imprint: preview failed", exc_info=True)
        return _error(f"preview failed: {exc}")


def import_history(args: dict, **kwargs) -> str:
    """Backfill from the profile's session store, read-only and bounded."""
    try:
        from . import importer

        days = int((args or {}).get("days") or 7)
        result = importer.import_window(days=days)
        return _ok(**result)
    except Exception as exc:
        logger.warning("imprint: import failed", exc_info=True)
        return _error(f"import refused or failed: {exc}")


def slash_command(raw_args: str = "", **kwargs) -> str:
    """``/imprint`` - the human door to the same pipeline."""
    tokens = (raw_args or "").split()
    try:
        if tokens and tokens[0].lower() == "burn":
            week = tokens[1] if len(tokens) > 1 else _current_week()
            payload = json.loads(burn_week({"week": week, "confirm": True}))
            if not payload.get("ok"):
                return payload.get("error", "burn failed")
            return f"Erased {week}. Rows, artefacts and bible entries are gone."

        if tokens and tokens[0].lower() == "library":
            return _library_summary()

        if len(tokens) >= 2 and tokens[0].lower() == "genre":
            return f"Genre set to {tokens[1]}. Recompile to re-typeset."

        if tokens and tokens[0].lower() == "status":
            payload = json.loads(ledger_status({}))
            if not payload.get("ok"):
                return payload.get("error", "status failed")
            return (
                f"{payload['events']} events across {len(payload['weeks'])} week(s). "
                f"Open threads: {payload['open_threads']}."
            )

        week = next((token for token in tokens if "-W" in token.upper()), _current_week())
        payload = json.loads(compile_week({"week": week}))
        if not payload.get("ok"):
            return payload.get("error", "compile failed")
        return (
            f"{payload.get('title', 'The Week')} is compiled: "
            f"{payload.get('chapters', 0)} chapters, "
            f"{payload.get('verified', 0)} of {payload.get('sentences', 0)} sentences verified."
        )
    except Exception as exc:
        logger.warning("imprint: command failed", exc_info=True)
        return f"imprint: {exc}"


def _library_summary() -> str:
    conn = _conn()
    rows = conn.execute(
        "SELECT week, title, genre, sentences_total, sentences_verified "
        "FROM books ORDER BY compiled_at DESC LIMIT 8"
    ).fetchall()
    if not rows:
        return "The shelf is empty. Run /imprint to compile the current week."
    lines = ["The shelf:"]
    for row in rows:
        lines.append(
            f"  {row['week']}  {row['title']}  ({row['genre']})  "
            f"{row['sentences_verified']}/{row['sentences_total']} verified"
        )
    return "\n".join(lines)


def _current_week() -> str:
    return datetime.now(timezone.utc).strftime("%G-W%V")


def _week_label(day: str) -> str:
    return datetime.fromisoformat(day).strftime("%G-W%V")


__all__ = [
    "burn_week",
    "compile_week",
    "import_history",
    "ledger_status",
    "preview_book",
    "slash_command",
    "schemas",
]
