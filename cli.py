"""``hermes imprint`` - the command-line door to the same pipeline.

Real work, from a terminal: compile a week, read the executive page, inspect
the ledger, erase a week. The agent tools and the slash command call the same
functions, so the demo is never a special build.
"""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def setup(parser) -> None:
    """Wire subcommands onto the ``hermes imprint`` parser."""
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="ledger size, weeks available, open threads")

    compile_parser = subparsers.add_parser("compile", help="compile a week into a book")
    compile_parser.add_argument("week", nargs="?", default=None, help="ISO week, e.g. 2026-W45")
    compile_parser.add_argument("--genre", default="epic", choices=("epic", "noir", "ships-log"))

    preview_parser = subparsers.add_parser("preview", help="print the executive page")
    preview_parser.add_argument("week", nargs="?", default=None)

    burn_parser = subparsers.add_parser("burn", help="erase a week permanently")
    burn_parser.add_argument("week")
    burn_parser.add_argument("--yes", action="store_true", help="confirm the erase")


def _pipeline():
    from . import pipeline

    return pipeline


def _current_week() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%G-W%V")


def handle(args: argparse.Namespace) -> int:
    """Dispatch one ``hermes imprint`` invocation."""
    from . import db

    command = getattr(args, "command", None) or "status"

    if command == "status":
        conn = db.connect()
        events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        weeks = [
            row[0]
            for row in conn.execute("SELECT DISTINCT substr(ts_utc, 1, 10) FROM events")
        ]
        labels = sorted({_week_label(day) for day in weeks})
        books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        print(f"ledger    {events} events across {len(labels)} week(s)")
        if labels:
            print(f"weeks     {', '.join(labels)}")
        print(f"books     {books} compiled")
        return 0

    if command == "compile":
        week = args.week or _current_week()
        result = _pipeline().compile_week(week, args.genre)
        print(f"{result['title']} - {week} ({result['genre']})")
        print(f"  chapters   {result['chapters']}")
        print(f"  sentences  {result['verified']} of {result['sentences']} carry a verified citation")
        print(f"  cut        {result['cut']}")
        print(f"  words      {result['words']}")
        print(f"  pdf        {result['pdf']}")
        print(f"  epub       {result['epub']}")
        return 0

    if command == "preview":
        week = args.week
        text = (
            _pipeline().executive_text_for_week(week)
            if week
            else _pipeline().executive_text(None)
        )
        if not text:
            print("no compiled book yet; run: hermes imprint compile")
            return 1
        print(text)
        return 0

    if command == "burn":
        if not args.yes:
            print("refusing to erase without --yes")
            return 1
        result = _pipeline().burn_week(args.week)
        print(f"erased {args.week}: {result}")
        return 0

    print(f"unknown command {command!r}")
    return 1


def _week_label(day: str) -> str:
    from datetime import datetime

    try:
        return datetime.fromisoformat(day).strftime("%G-W%V")
    except ValueError:
        return day
