"""Desktop and dashboard backend for Imprint, mounted at /api/plugins/imprint/.

Read-only routes serve the shelf and the executive page. The compile route is
the only writer, and it is the same pipeline the agent tool runs - no second
implementation, no divergent behaviour.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

ROOT = Path(__file__).resolve().parent.parent
_PACKAGE = "imprint_backend"

_compile_lock = threading.Lock()
_compile_state: dict = {"state": "idle", "week": None, "started_at": None, "error": None}


def _pipeline():
    """Resolve the plugin's own pipeline module inside the gateway process.

    The gateway already loaded the plugin under its registry key; use that copy
    when it is there, and load a private one from this file's parent when it is
    not (a desktop-only enable, or a dashboard-only mount).
    """
    for name, module in list(sys.modules.items()):
        if getattr(module, "__file__", None) == str(ROOT / "__init__.py"):
            return sys.modules.get(f"{name}.pipeline")

    if _PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            _PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("imprint: cannot load its own package")
        module = importlib.util.module_from_spec(spec)
        sys.modules[_PACKAGE] = module
        spec.loader.exec_module(module)

    return sys.modules.get(f"{_PACKAGE}.pipeline")


@router.get("/books")
async def books() -> dict:
    """The shelf: every compiled week, newest first."""
    try:
        import sqlite3

        from plugins.plugin_storage import plugin_db

        conn = plugin_db("imprint")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, week, title, genre, compiled_at, pdf_path, epub_path, html_path, "
            "sentences_total, sentences_verified FROM books ORDER BY compiled_at DESC LIMIT 52"
        ).fetchall()
        return {
            "ok": True,
            "books": [dict(row) for row in rows],
            "compile": dict(_compile_state),
        }
    except Exception as exc:  # a broken shelf must not take the page down
        return {"ok": False, "error": str(exc), "books": [], "compile": dict(_compile_state)}


@router.get("/books/{week}")
async def book(week: str) -> dict:
    """One week: its chapters, its cast, and its verification ratio."""
    try:
        import json
        import sqlite3

        from plugins.plugin_storage import plugin_db

        conn = plugin_db("imprint")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM books WHERE week = ?", (week,)).fetchone()
        if row is None:
            return {"ok": False, "error": f"no book for {week}"}

        chapters = conn.execute(
            "SELECT ordinal, title, genre, body_md, citations_json, verified_ratio, word_count "
            "FROM chapters WHERE book_id = ? ORDER BY ordinal",
            (row["id"],),
        ).fetchall()

        return {
            "ok": True,
            "book": dict(row),
            "chapters": [
                {
                    **dict(chapter),
                    "citations": json.loads(chapter["citations_json"] or "[]"),
                }
                for chapter in chapters
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/executive")
async def executive(week: str | None = None) -> dict:
    """Shipped, blocked, owed, spend - the Friday report."""
    try:
        pipeline = _pipeline()
        if pipeline is None:
            return {"ok": False, "error": "pipeline not available"}

        if week is None:
            text = pipeline.executive_text(None)
            return {"ok": bool(text), "text": text}

        return {"ok": True, "text": pipeline.executive_text_for_week(week)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/compile")
async def compile_week(body: dict | None = None) -> dict:
    """Compile in the background so the page keeps answering."""
    body = body or {}
    week = body.get("week")
    genre = body.get("genre")

    if _compile_lock.locked():
        return {"ok": False, "error": "a compile is already running", "compile": dict(_compile_state)}

    def run() -> None:
        import datetime

        with _compile_lock:
            _compile_state.update(
                {
                    "state": "running",
                    "week": week,
                    "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    "error": None,
                }
            )
            try:
                pipeline = _pipeline()
                if pipeline is None:
                    raise RuntimeError("pipeline not available")

                week_to_build = week or _current_week()
                pipeline.compile_week(week_to_build, genre or "epic")
                _compile_state.update({"state": "done", "week": week_to_build})
            except Exception as exc:
                _compile_state.update({"state": "failed", "error": str(exc)})

    threading.Thread(target=run, name="imprint-compile", daemon=True).start()
    return {"ok": True, "state": "started", "week": week}


def _current_week() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%G-W%V")


@router.post("/burn")
async def burn(body: dict | None = None) -> dict:
    """Erase one week. The page asks first; so does the tool."""
    body = body or {}
    week = body.get("week")
    if not week:
        return {"ok": False, "error": "which week?"}

    try:
        pipeline = _pipeline()
        if pipeline is None:
            return {"ok": False, "error": "pipeline not available"}
        return {"ok": True, **pipeline.burn_week(week)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
