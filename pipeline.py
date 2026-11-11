"""Orchestration: ledger in, book out.

This is the only module that knows the order of the stages. Every stage is
deterministic except prose, and prose is gated by the canon checker before it
reaches a page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import arcs, canon, cast, db, prose, redact

logger = logging.getLogger(__name__)

GENRES = tuple(prose.GENRES)


# --------------------------------------------------------------------------
# compile
# --------------------------------------------------------------------------


def compile_week(week: str, genre: str = "epic", llm=None, settings: dict | None = None) -> dict:
    """Build one week's book end to end."""
    settings = settings or {}
    if genre not in GENRES:
        raise ValueError(f"unknown genre {genre!r}")

    conn = db.connect()
    events = arcs.load_events(conn, week)
    if not events:
        raise ValueError(
            f"no events recorded for {week}. Compile a week after it has happened, "
            "or run imprint_import to backfill from the session store."
        )

    quests = arcs.split_quests(events)
    chapters: list[dict] = []
    chapter_rows: list[tuple] = []

    _store_quests(conn, week, quests)

    ask = _ask_for(llm)
    cache_dir = _data_dir() / "cache"
    events_by_id = {f"e{row['id']}": row for row in events}
    model_error: str | None = None

    ordered = sorted(quests, key=arcs.stakes, reverse=True)
    used_titles: set[str] = set()
    for quest in ordered:
        label = arcs._quest_label(quest)
        for chapter in arcs.build_chapters(quest):
            try:
                body = prose.write_chapter(
                    llm=llm,
                    genre=genre,
                    chapter=chapter,
                    quest_label=label,
                    week=week,
                    event_rows=chapter["events"],
                    cache_dir=cache_dir if llm is not None else None,
                )
            except Exception as exc:
                # A configured model that refuses (no credit, bad key, rate limit)
                # must not cost the user their book. Print the offline edition and
                # say so in the colophon.
                if model_error is None:
                    model_error = str(exc).strip().splitlines()[0][:200]
                    logger.warning("imprint: model unavailable, printing offline edition: %s", model_error)
                llm = None
                ask = None
                body = prose.write_chapter(
                    llm=None,
                    genre=genre,
                    chapter=chapter,
                    quest_label=label,
                    week=week,
                    event_rows=chapter["events"],
                )
            allowed = {f"e{row['id']}" for row in chapter["events"]}
            verdict = canon.verify(body, allowed, events_by_id, ask=ask)

            title = prose.chapter_title(genre, chapter["label"], len(chapters) + 1, label)
            if title in used_titles:
                day = _weekday_name(events_by_id[f"e{chapter['events'][0]['id']}"])
                candidate = f"{title} ({day})" if day else title
                title = candidate if candidate not in used_titles else f"{title} (continued)"
            used_titles.add(title)
            chapters.append(
                {
                    "ordinal": len(chapters) + 1,
                    "title": title,
                    "label": chapter["label"],
                    "quest": label,
                    "body": verdict["body"],
                    "citations": _cited_events(verdict["body"], events_by_id),
                    "sentences_total": verdict["sentences_total"],
                    "sentences_verified": verdict["sentences_verified"],
                    "verified_ratio": verdict["verified_ratio"],
                    "cut": verdict["cut"],
                    "stakes": chapter["stakes"],
                    "start_day": _day_index(chapter["events"]),
                    "span": _day_span(chapter["events"]),
                }
            )
            chapter_rows.append(
                (
                    title,
                    genre,
                    verdict["body"],
                    json.dumps([item["id"] for item in chapters[-1]["citations"]]),
                    verdict["verified_ratio"],
                    len(verdict["body"].split()),
                )
            )

    if not chapters:
        raise ValueError(f"{week} has events but no chapters; nothing worth printing yet")

    totals = {
        "sentences": sum(chapter["sentences_total"] for chapter in chapters),
        "verified": sum(chapter["sentences_verified"] for chapter in chapters),
        "cut": sum(len(chapter["cut"]) for chapter in chapters),
        "words": sum(len(chapter["body"].split()) for chapter in chapters),
    }

    book_data = _book_data(week, genre, settings, events, quests, chapters, totals, llm)
    book_data["colophon"]["build_hash"] = _build_hash(book_data, events)
    if model_error:
        book_data["colophon"]["mode"] = "offline"
        book_data["colophon"]["mode_text"] = (
            "Offline edition: the configured model was unavailable ("
            + model_error
            + "), so the prose was composed deterministically from the ledger."
        )

    from .typeset import render

    paths = render.write_book(book_data)

    book_id = _store_book(conn, week, book_data, chapter_rows, paths, totals)
    return {
        "book_id": book_id,
        "week": week,
        "title": book_data["title"],
        "genre": genre,
        "chapters": len(chapters),
        "sentences": totals["sentences"],
        "verified": totals["verified"],
        "cut": totals["cut"],
        "words": totals["words"],
        "verified_ratio": round(totals["verified"] / totals["sentences"], 3)
        if totals["sentences"]
        else 0.0,
        "mode": book_data["colophon"]["mode"],
        "model_error": model_error,
        "pdf": paths.get("pdf"),
        "epub": paths.get("epub"),
        "html": paths.get("html"),
        "engine": paths.get("engine"),
    }


def _ask_for(llm):
    """The canon checker's cheap model call, or None when there is no LLM."""
    if llm is None:
        return None

    def ask(prompt: str) -> str:
        result = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=700,
            temperature=0.0,
            purpose="imprint.canon",
        )
        return getattr(result, "text", "") or ""

    return ask


# --------------------------------------------------------------------------
# executive edition
# --------------------------------------------------------------------------


def executive_summary(week: str) -> dict:
    """Shipped, blocked, owed, spend, hours - recomputed from the ledger."""
    conn = db.connect()
    events = arcs.load_events(conn, week)
    quests = arcs.split_quests(events)

    shipped = _unique(
        [arcs._quest_label(quest) for quest in quests if arcs.quest_status(quest) == "done"]
    )
    blocked = _unique(
        [arcs._quest_label(quest) for quest in quests if arcs.quest_status(quest) == "stalled"]
    )

    owed: list[str] = []
    for quest in quests:
        label = arcs._quest_label(quest)
        waiting: dict[str, bool] = {}
        for event in quest:
            if event.get("kind") != "approval":
                continue
            category = str(event.get("target") or "an approval")
            if event.get("outcome") == "pending":
                waiting[category] = True
            else:
                waiting.pop(category, None)
        for category in waiting:
            owed.append(f"{label}: {category} is still waiting")

        todo_events = [
            event
            for event in quest
            if event.get("action") == "write" and "todo" in (event.get("target") or "").lower()
        ]
        if todo_events:
            last_todo = todo_events[-1]
            if last_todo.get("outcome") != "ok" or len(todo_events) == 1:
                owed.append(f"{label}: an open todo")

    spend = sum(float(event.get("cost_usd") or 0.0) for event in events)
    hours = 0.0
    for quest in quests:
        first = _parse(quest[0]["ts_utc"])
        last = _parse(quest[-1]["ts_utc"])
        if first and last:
            hours += (last - first).total_seconds() / 3600.0

    return {
        "week": week,
        "shipped": shipped,
        "blocked": blocked,
        "owed": owed,
        "spend_usd": round(spend, 4),
        "hours": round(hours, 1),
        "events": len(events),
        "quests": len(quests),
    }


def _unique(values: list[str]) -> list[str]:
    """Preserve order, drop repeats - a project is named once in the report."""
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def executive_text(book_id: int | None = None) -> str:
    """The executive page as plain text."""
    week = _week_for_book(book_id)
    if not week:
        return ""
    return executive_text_for_week(week)


def executive_text_for_week(week: str) -> str:
    """The executive page for a named week, without opening the book."""
    summary = executive_summary(week)
    return _format_executive(summary)


def _format_executive(summary: dict) -> str:
    lines = [
        f"IMPRINT - {summary['week']}",
        "",
        f"Shipped ({len(summary['shipped'])}): " + (", ".join(summary["shipped"][:8]) or "nothing"),
        f"Blocked ({len(summary['blocked'])}): " + (", ".join(summary["blocked"][:8]) or "nothing"),
        f"Owed ({len(summary['owed'])}): " + ("; ".join(summary["owed"][:8]) or "nothing"),
        f"Spend: ${summary['spend_usd']:.2f}",
        f"Hours: {summary['hours']}",
        f"Events: {summary['events']} across {summary['quests']} quests",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# burn
# --------------------------------------------------------------------------


def burn_week(week: str) -> dict:
    """Delete a week completely: rows, artefacts, bible entries."""
    conn = db.connect()
    start, end = arcs.week_bounds(week)

    rows = conn.execute(
        "SELECT pdf_path, epub_path, html_path FROM books WHERE week = ?", (week,)
    ).fetchall()

    removed_files = 0
    for row in rows:
        for key in ("pdf_path", "epub_path", "html_path"):
            path = row[key]
            if not path:
                continue
            try:
                Path(path).unlink(missing_ok=True)
                removed_files += 1
            except OSError:
                logger.warning("imprint: could not delete %s", path, exc_info=True)

    deleted_events = conn.execute(
        "DELETE FROM events WHERE ts_utc >= ? AND ts_utc < ?", (start, end)
    ).rowcount
    deleted_chapters = conn.execute(
        "DELETE FROM chapters WHERE book_id IN (SELECT id FROM books WHERE week = ?)", (week,)
    ).rowcount
    deleted_books = conn.execute("DELETE FROM books WHERE week = ?", (week,)).rowcount
    deleted_quests = conn.execute("DELETE FROM quests WHERE week = ?", (week,)).rowcount
    deleted_bible = conn.execute(
        "DELETE FROM bible WHERE first_seen >= ? AND first_seen < ?", (start, end)
    ).rowcount
    conn.commit()

    return {
        "events": deleted_events,
        "chapters": deleted_chapters,
        "books": deleted_books,
        "quests": deleted_quests,
        "bible": deleted_bible,
        "files": removed_files,
    }


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------


def _store_quests(conn, week: str, quests: list[list[dict]]) -> None:
    conn.execute("DELETE FROM quests WHERE week = ?", (week,))
    for quest in quests:
        summary = arcs.quest_summary(quest)
        conn.execute(
            "INSERT INTO quests (week, key, label, first_ts, last_ts, stakes, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                week,
                summary["key"],
                summary["label"],
                summary["first_ts"],
                summary["last_ts"],
                summary["stakes"],
                summary["status"],
            ),
        )
    conn.commit()


def _store_book(conn, week, book_data, chapters, paths, totals) -> int:
    conn.execute("DELETE FROM books WHERE week = ?", (week,))
    cursor = conn.execute(
        "INSERT INTO books (week, title, genre, compiled_at, pdf_path, epub_path, html_path, "
        "sentences_total, sentences_verified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            week,
            book_data["title"],
            book_data["genre"],
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            paths.get("pdf"),
            paths.get("epub"),
            paths.get("html"),
            totals["sentences"],
            totals["verified"],
        ),
    )
    book_id = cursor.lastrowid
    conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
    for ordinal, (title, genre, body, citations_json, ratio, words) in enumerate(chapters, start=1):
        conn.execute(
            "INSERT INTO chapters (book_id, ordinal, title, genre, body_md, citations_json, "
            "verified_ratio, word_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (book_id, ordinal, title, genre, body, citations_json, ratio, words),
        )
    conn.commit()
    return book_id


def _week_for_book(book_id: int | None) -> str | None:
    conn = db.connect()
    if book_id is None:
        row = conn.execute("SELECT week FROM books ORDER BY compiled_at DESC LIMIT 1").fetchone()
    else:
        row = conn.execute("SELECT week FROM books WHERE id = ?", (book_id,)).fetchone()
    return row["week"] if row else None


def _book_data(week, genre, settings, events, quests, chapters, totals, llm=None) -> dict:
    title = settings.get("book_title") or "The Week"
    start, _ = arcs.week_bounds(week)
    first = datetime.fromisoformat(start)
    last = first + timedelta(days=6)
    ratio = totals["verified"] / totals["sentences"] if totals["sentences"] else 0.0

    return {
        "title": title,
        "week": week,
        "edition": int(week[-2:]),
        "genre": genre,
        "genre_label": prose.GENRES[genre]["label"],
        "range": _range_text(first, last),
        "exec": executive_summary(week),
        "chapters": chapters,
        "cast": cast.build(events),
        "motifs": arcs.motifs(events),
        "appendix": _cited_appendix(chapters, events),
        "colophon": {
            "events": len(events),
            "quests": len(quests),
            "chapters": len(chapters),
            "sentences": totals["sentences"],
            "verified": totals["verified"],
            "cut": totals["cut"],
            "ratio": round(ratio, 3),
            "mode": "offline" if llm is None else "model",
            "mode_text": (
                "Prose written by the configured model and checked against the ledger."
                if llm is not None
                else "Offline edition: prose composed deterministically from the ledger. "
                "No model was called."
            ),
            "ratio_text": (
                f"{totals['verified']} of {totals['sentences']} sentences carry a verified "
                f"citation. {totals['cut']} were cut."
            ),
            "build_hash": "",
            "privacy": (
                "Imprint records locally. Summaries are redacted before they are written, "
                "excluded paths are never recorded, and nothing leaves this machine except "
                "the model calls you already configured."
            ),
        },
    }


def _cited_appendix(chapters: list[dict], events: list[dict]) -> list[dict]:
    """The appendix lists the events the book actually cited, in order."""
    by_id = {f"e{row['id']}": row for row in events}
    first_chapter: dict[str, int] = {}

    for chapter in chapters:
        ordinal = int(chapter.get("ordinal") or 0)
        for citation in chapter.get("citations") or []:
            first_chapter.setdefault(citation["id"], ordinal)

    cited = sorted(first_chapter, key=lambda event_id: int(event_id[1:]))
    appendix = []
    for event_id in cited:
        row = by_id.get(event_id)
        if not row:
            continue
        appendix.append(
            {
                "id": event_id,
                "ts": row["ts_utc"],
                "day": row["ts_utc"][:10],
                "chapter": first_chapter[event_id],
                "summary": row.get("summary")
                or f"{row.get('tool') or row.get('kind')} on {row.get('target') or 'unknown'}",
            }
        )
    return appendix


def _build_hash(book_data: dict, events: list[dict]) -> str:
    material = json.dumps(
        {
            "week": book_data["week"],
            "genre": book_data["genre"],
            "titles": [chapter["title"] for chapter in book_data["chapters"]],
            "events": [event["event_id"] for event in events],
        },
        sort_keys=True,
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def _cited_events(body: str, events_by_id: dict[str, dict]) -> list[dict]:
    seen: list[str] = []
    for event_id in canon.cited_ids(body):
        if event_id not in seen:
            seen.append(event_id)
    return [
        {
            "id": event_id,
            "ts": events_by_id[event_id].get("ts_utc"),
            "summary": events_by_id[event_id].get("summary")
            or events_by_id[event_id].get("target")
            or "",
        }
        for event_id in seen
        if event_id in events_by_id
    ]


def _data_dir() -> Path:
    """The plugin's data directory, with a test seam.

    ``IMPRINT_DATA_DIR`` lets the golden test compile into a temporary
    directory without Hermes in the process. Production always goes through
    Hermes' own per-plugin data root.
    """
    override = os.environ.get("IMPRINT_DATA_DIR")
    if override:
        return Path(override)

    from plugins.plugin_storage import plugin_data_dir

    return Path(plugin_data_dir(db.PLUGIN_NAME))


def _parse(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _range_text(first: datetime, last: datetime) -> str:
    """A date range a person would write on a cover."""
    if first.month == last.month:
        return f"{first.day}\u2013{last.day} {last.strftime('%B %Y')}"
    return f"{first.day} {first.strftime('%B')} \u2013 {last.day} {last.strftime('%B %Y')}"


def _day_index(events: list[dict]) -> int:
    """Weekday the chapter starts on, for the map."""
    for event in events:
        parsed = _parse(event.get("ts_utc"))
        if parsed:
            return max(0, min(6, parsed.weekday()))
    return 0


def _weekday_name(event: dict) -> str:
    parsed = _parse(event.get("ts_utc"))
    return parsed.strftime("%A") if parsed else ""


def _day_span(events: list[dict]) -> int:
    """How many days the chapter covers, clamping to the week's edge."""
    days = [parsed for parsed in (_parse(event.get("ts_utc")) for event in events) if parsed]
    if not days:
        return 1

    span = (max(days).date() - min(days).date()).days + 1
    return max(1, min(span, 7 - _day_index(events)))
