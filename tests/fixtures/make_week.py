"""Generate the fixture week.

Deterministic on purpose: the same bytes every run, so a golden test that
passes today still passes after a refactor. The week is built to contain one
of each act break the extractor knows about.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

START = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)  # Monday, ISO week 45

Error = "ModuleNotFoundError: No module named 'typst'"


def event(minutes: int, **fields) -> dict:
    ts = (START + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return {
        "ts_utc": ts,
        "session_id": fields.pop("session_id", "sess-a"),
        "turn_id": fields.pop("turn_id", "turn-1"),
        "subagent_id": fields.pop("subagent_id", None),
        "kind": fields.pop("kind", "tool"),
        "actor": fields.pop("actor", "agent"),
        "tool": fields.pop("tool", None),
        "target": fields.pop("target", None),
        "action": fields.pop("action", "read"),
        "outcome": fields.pop("outcome", "ok"),
        "exit_code": fields.pop("exit_code", None),
        "duration_ms": fields.pop("duration_ms", 1200),
        "cost_usd": fields.pop("cost_usd", None),
        "tokens_in": fields.pop("tokens_in", None),
        "tokens_out": fields.pop("tokens_out", None),
        "summary": fields.pop("summary", None),
        "error_sig": fields.pop("error_sig", None),
        "redacted": fields.pop("redacted", 0),
        "raw_ref": None,
    }


def week() -> list[dict]:
    rows: list[dict] = []

    # Quest A - the typst install that would not work, then did.
    rows += [
        event(0, tool="write_file", target="C:/work/imprint-plugin/typeset/book.typ", action="write", summary="wrote book template"),
        event(6, tool="write_file", target="C:/work/imprint-plugin/typeset/render.py", action="write", summary="wrote renderer"),
        event(12, tool="shell", target="C:/work/imprint-plugin", action="exec", outcome="fail", exit_code=1,
              summary="typst not found", error_sig=Error),
        event(18, tool="shell", target="C:/work/imprint-plugin", action="exec", outcome="fail", exit_code=1,
              summary="typst not found", error_sig=Error),
        event(24, tool="shell", target="C:/work/imprint-plugin", action="exec", outcome="fail", exit_code=1,
              summary="typst not found", error_sig=Error),
        event(31, tool="shell", target="C:/work/imprint-plugin", action="exec", outcome="ok",
              summary="installed typst 0.13.1"),
        event(38, tool="write_file", target="C:/work/imprint-plugin/tests/test_typeset.py", action="write",
              summary="wrote golden test"),
    ]

    # Quest B - a blocked send that needed a person.
    rows += [
        event(70, tool="send_email", target="invoices.example.club", action="send", outcome="blocked",
              summary="blocked: outbound send needs approval", session_id="sess-b"),
        event(74, kind="approval", actor="human", action="approve", outcome="pending",
              target="outbound_send", summary="approval requested: outbound_send (cli)", session_id="sess-b"),
        event(76, kind="approval", actor="human", action="approve", outcome="ok",
              target="outbound_send", summary="approval once (cli)", session_id="sess-b"),
        event(80, tool="send_email", target="invoices.example.club", action="send", outcome="ok",
              summary="invoice 4471 sent", session_id="sess-b"),
    ]

    # Quest C - same project, a two-hour gap later, left unfinished.
    rows += [
        event(260, tool="read_file", target="C:/work/imprint-plugin/README.md", action="read",
              summary="read README"),
        event(266, tool="shell", target="C:/work/imprint-plugin", action="exec", outcome="fail",
              exit_code=1, summary="validate --ci failed: catalog metadata", error_sig="ValidationError: missing sha"),
        event(270, tool="write_file", target="C:/work/imprint-plugin/TODO.md", action="write",
              summary="wrote TODO: bump sha before PR"),
    ]

    # Quest D - a subagent hand-off that never came back.
    rows += [
        event(400, kind="message", actor="agent", action="delegate", target="sub-docs",
              summary="delegated chapter titles to @hermes-docs", session_id="sess-d"),
        event(405, kind="message", actor="subagent", action="delegate", outcome="pending",
              target="sub-docs", subagent_id="sub-1", summary="child still running", session_id="sess-d"),
    ]

    # A motif: the same failure four times across the week.
    rows += [
        event(500, tool="shell", target="C:/work/imprint-plugin/tests", action="exec", outcome="fail",
              exit_code=1, summary="test failed: assertion", error_sig=Error, session_id="sess-a"),
        event(506, tool="shell", target="C:/work/imprint-plugin/tests", action="exec", outcome="fail",
              exit_code=1, summary="test failed: assertion", error_sig=Error, session_id="sess-a"),
    ]

    return rows


def main() -> None:
    target = Path(__file__).parent / "week.json"
    target.write_text(json.dumps(week(), indent=2), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
