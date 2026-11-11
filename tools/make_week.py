"""Fabricate a realistic week of Hermes activity, for demos and golden tests.

This is demo data. Every row is invented: repositories, errors, approvals,
quotes and spend. It is shaped like a real week - one main repo, several side
quests, failures that turn, an approval denied, a subagent, a cron report, a
deploy that goes wrong and a Friday that goes right.

Summaries are written as human clauses on purpose. The composer reads them,
so a richer summary is a richer sentence in the book.

    python tools/make_week.py --out .demo-profile
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

_PACKAGE = "imprint_plugin"
if _PACKAGE not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_PACKAGE] = _module
    _spec.loader.exec_module(_module)

from imprint_plugin import db  # noqa: E402

WEEK = "2026-W45"
MONDAY = datetime(2026, 11, 2, 8, 50, tzinfo=timezone.utc)

API = "C:/work/atlas-api"
WEB = "C:/work/atlas-web"
OPS = "C:/work/ops/terraform"
INVOICE = "github.com/example/invoice-service"

LOCK = "OperationalError: could not obtain lock on queue_jobs after 90s"
HEALTH = "TimeoutError: /healthz did not answer within 90s"
GATEWAY = "AssertionError: expected status 200, got 502"


class Week:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.turn_count: dict[str, int] = {}

    def add(
        self,
        at: datetime,
        session: str,
        summary: str,
        *,
        tool: str | None = None,
        target: str | None = None,
        action: str = "read",
        outcome: str = "ok",
        kind: str = "tool",
        actor: str = "agent",
        error: str | None = None,
        exit_code: int | None = 0,
        minutes: int = 2,
        subagent: str | None = None,
        cost: float | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        model: str | None = None,
    ) -> None:
        turn = self.turn_count.get(session, 0)
        if tool == "terminal" or kind == "llm":
            turn += 1
            self.turn_count[session] = turn

        self.rows.append(
            {
                "ts_utc": at.isoformat(timespec="seconds"),
                "session_id": session,
                "turn_id": f"{session}-t{turn}",
                "subagent_id": subagent,
                "kind": kind,
                "actor": actor,
                "tool": model or tool,
                "target": target,
                "action": action,
                "outcome": outcome,
                "exit_code": exit_code if kind == "tool" else None,
                "duration_ms": minutes * 60_000 if kind == "tool" else None,
                "cost_usd": cost,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "summary": summary,
                "error_sig": error,
                "redacted": 0,
                "raw_ref": None,
            }
        )

    def turn(self, at: datetime, session: str, cost: float, tin: int, tout: int) -> None:
        self.add(
            at,
            session,
            "the model was asked to weigh the next step",
            kind="llm",
            target="nous-portal",
            action="call",
            cost=cost,
            tokens_in=tin,
            tokens_out=tout,
            model="claude-opus-4.6",
        )

    def approval(self, at: datetime, session: str, category: str, choice: str) -> None:
        readable = category.replace("_", " ")
        week_summary = f"someone was asked to allow {readable}"
        verdict = {
            "once": "the request for " + readable + " was granted once",
            "session": "the request for " + readable + " was granted for the session",
            "always": "the request for " + readable + " was granted for good",
            "deny": "the request for " + readable + " was refused",
        }.get(choice, f"the request for {readable} came back {choice}")

        self.add(
            at,
            session,
            week_summary,
            kind="approval",
            actor="human",
            action="approve",
            outcome="pending",
            target=category,
        )
        self.add(
            at + timedelta(minutes=1),
            session,
            verdict,
            kind="approval",
            actor="human",
            action="approve",
            outcome="ok" if choice in {"once", "session", "always"} else "blocked",
            target=category,
        )

    def read(self, at, session, path, summary, minutes=1):
        self.add(at, session, summary, tool="read_file", target=path, minutes=minutes)

    def write(self, at, session, path, summary, minutes=2):
        self.add(at, session, summary, tool="write_file", target=path, action="write", minutes=minutes)

    def edit(self, at, session, path, summary, minutes=2):
        self.add(at, session, summary, tool="edit_file", target=path, action="write", minutes=minutes)

    def run(self, at, session, target, summary, *, ok=True, error=None, out=1, minutes=2):
        self.add(
            at,
            session,
            summary,
            tool="terminal",
            target=target,
            action="exec",
            outcome="ok" if ok else "fail",
            error=error,
            exit_code=0 if ok else out,
            minutes=minutes,
        )

    def search(self, at, session, query, summary):
        self.add(at, session, summary, tool="web_search", target=query, minutes=1)

    def fetch(self, at, session, url, summary):
        self.add(at, session, summary, tool="web_fetch", target=url, minutes=1)

    def message(self, at, session, target, summary, *, actor="agent"):
        self.add(at, session, summary, kind="message", target=target, action="write", actor=actor)


def monday(week: Week) -> None:
    s = "s-mon"
    b = MONDAY

    week.read(b + timedelta(minutes=10), s, f"{API}/README.md", "the README described a queue that had once been reliable")
    week.read(b + timedelta(minutes=14), s, f"{API}/docs/ARCHITECTURE.md", "the architecture notes blamed the lock, not the worker")
    week.read(b + timedelta(minutes=18), s, f"{API}/src/queue.py", "queue.py held the lock for the whole batch")
    week.search(b + timedelta(minutes=22), s, "postgres advisory lock timeout", "the search turned up a dozen people with the same scar")
    week.turn(b + timedelta(minutes=27), s, 0.022, 8400, 610)

    week.write(b + timedelta(minutes=33), s, f"{API}/src/locks.py", "a small lock helper was written, with a timeout that could be argued with")
    week.write(b + timedelta(minutes=38), s, f"{API}/tests/test_locks.py", "the helper got a test before it got trust")
    week.edit(b + timedelta(minutes=44), s, f"{API}/src/queue.py", "queue.py was taught to ask for the lock and give up politely")

    for attempt in range(4):
        week.run(
            b + timedelta(minutes=50 + attempt * 4),
            s,
            API,
            "pytest stopped where it always stopped: the worker still held the lock"
            if attempt < 3
            else "pytest stopped again, now on the timeout itself",
            ok=False,
            error=LOCK,
        )

    week.read(b + timedelta(minutes=70), s, f"{API}/tests/test_queue.py", "the test asserted that the lock had been held, which was the bug written down")
    week.edit(b + timedelta(minutes=74), s, f"{API}/tests/test_queue.py", "the assertion was loosened to the thing that actually mattered")
    week.run(b + timedelta(minutes=80), s, API, "pytest went green for the first time that morning", minutes=3)
    week.turn(b + timedelta(minutes=86), s, 0.031, 15200, 940)

    week.approval(b + timedelta(minutes=95), s, "database_migration", "once")
    week.run(b + timedelta(minutes=99), s, API, "the migration ran and said nothing", minutes=4)
    week.run(b + timedelta(minutes=106), s, API, "the worker drained its backlog without holding anything", minutes=3)
    week.write(b + timedelta(minutes=114), s, f"{API}/docs/locks.md", "the lock notes were written down while they were still fresh")
    week.message(b + timedelta(minutes=120), s, "standup", '"Lock is fixed. Migration is applied to staging. I want one quiet hour before I believe it."')
    week.turn(b + timedelta(minutes=126), s, 0.018, 6200, 480)

    # The web app, after lunch.
    w = "s-mon-web"
    week.run(b + timedelta(minutes=196), w, WEB, "the web tests ran and mostly agreed with themselves", minutes=2)
    week.run(
        b + timedelta(minutes=202),
        w,
        WEB,
        "one test asked the gateway for a 200 and got a 502",
        ok=False,
        error=GATEWAY,
    )
    week.read(b + timedelta(minutes=208), w, f"{WEB}/src/api/client.ts", "the client retried nothing and reported everything")
    week.edit(b + timedelta(minutes=213), w, f"{WEB}/src/api/client.ts", "the client was given one retry and a shorter temper")
    week.run(b + timedelta(minutes=219), w, WEB, "the web tests came back green", minutes=2)
    week.turn(b + timedelta(minutes=224), w, 0.012, 5100, 390)


def tuesday(week: Week) -> None:
    s = "s-tue"
    b = MONDAY + timedelta(days=1, minutes=5)

    week.read(b, s, f"{API}/src/locks.py", "the helper from yesterday was read again with suspicion")
    week.read(b + timedelta(minutes=5), s, f"{API}/src/queue.py", "queue.py was read for the places the lock leaked")
    week.run(b + timedelta(minutes=9), s, API, "git diff showed forty lines, which was thirty too many")
    week.search(b + timedelta(minutes=14), s, "redis lock renewal best practices", "the search suggested renewing instead of extending, which was a different shape of fix")
    week.turn(b + timedelta(minutes=19), s, 0.026, 9100, 720)

    week.approval(b + timedelta(minutes=31), s, "destructive_shell", "deny")
    week.add(
        b + timedelta(minutes=33),
        s,
        "the cache was nearly deleted with a command nobody wanted to approve",
        tool="terminal",
        target=API,
        action="exec",
        outcome="blocked",
        error="ApprovalDenied: destructive_shell",
        exit_code=126,
        minutes=0,
    )
    week.run(b + timedelta(minutes=36), s, API, "the cache was cleared the narrow way instead", minutes=1)
    week.edit(b + timedelta(minutes=42), s, f"{API}/src/locks.py", "the helper learned to renew a lock it still owned")

    week.add(
        b + timedelta(minutes=52),
        s,
        "the changelog was handed to another agent and told to be brief",
        kind="message",
        target="sub-docs",
        action="delegate",
        subagent="sub-1",
    )
    week.add(
        b + timedelta(minutes=55),
        s,
        "the child agent was still reading when the parent moved on",
        kind="message",
        target="sub-docs",
        action="delegate",
        outcome="pending",
        subagent="sub-1",
        actor="subagent",
    )
    week.add(
        b + timedelta(minutes=94),
        s,
        "the changelog came back with three entries and no adjectives",
        kind="message",
        target="sub-docs",
        action="delegate",
        subagent="sub-1",
        actor="subagent",
    )
    week.turn(b + timedelta(minutes=102), s, 0.032, 11800, 830)

    week.run(b + timedelta(minutes=112), s, API, "the suite ran twice and passed twice", minutes=4)
    week.message(b + timedelta(minutes=118), s, "standup", '"Lock renews now. Cache cleared without incident. Reviewing the invoice PR next."')

    # The invoice service review.
    r = "s-tue-review"
    week.run(b + timedelta(minutes=150), r, INVOICE, "the review branch came down clean", minutes=1)
    week.read(b + timedelta(minutes=154), r, f"{INVOICE}/billing/invoice.py", "invoice.py rounded twice, once on purpose and once by accident")
    week.read(b + timedelta(minutes=159), r, f"{INVOICE}/tests/test_invoice.py", "the tests rounded nothing at all")
    week.run(
        b + timedelta(minutes=164),
        r,
        INVOICE,
        "the invoice tests failed where the rounding disagreed with itself",
        ok=False,
        error=GATEWAY,
    )
    week.message(b + timedelta(minutes=170), r, f"{INVOICE}/PR-214", '"Two comments. The rounding is inconsistent between the total and the line items, and there is no test for the refund path."')
    week.run(
        b + timedelta(minutes=177),
        r,
        INVOICE,
        "the tests failed again after the review, which is what a review is for",
        ok=False,
        error=GATEWAY,
    )
    week.turn(b + timedelta(minutes=184), r, 0.019, 7400, 520)


def wednesday(week: Week) -> None:
    s = "s-wed"
    b = MONDAY + timedelta(days=2, minutes=10)

    week.run(b + timedelta(minutes=8), s, OPS, "terraform plan was uneventful, which never lasts")
    for attempt in range(3):
        week.run(
            b + timedelta(minutes=16 + attempt * 7),
            s,
            OPS,
            "the staging deploy went up and the health check never answered"
            if attempt == 0
            else "the deploy was retried and the health check stayed silent",
            ok=False,
            error=HEALTH,
            minutes=4,
        )

    week.read(b + timedelta(minutes=44), s, f"{OPS}/modules/service/main.tf", "the service module gave the container ten seconds to live")
    week.approval(b + timedelta(minutes=54), s, "infrastructure_apply", "session")
    week.edit(b + timedelta(minutes=59), s, f"{OPS}/modules/service/main.tf", "the grace period was raised and the probe was made to wait")
    week.run(b + timedelta(minutes=70), s, OPS, "the deploy went up and stayed up", minutes=6)
    week.run(b + timedelta(minutes=79), s, OPS, "the health check answered on the first ask", minutes=1)
    week.turn(b + timedelta(minutes=88), s, 0.038, 16100, 1180)

    week.message(b + timedelta(minutes=96), s, "incidents", '"Staging deploy failed three times on the health probe. Grace period was ten seconds. It is now forty. Service is up."')
    week.write(b + timedelta(minutes=104), s, f"{OPS}/docs/incident-2026-11-04.md", "the incident note was written while the timeline was still in memory")
    week.add(
        b + timedelta(minutes=116),
        s,
        "the lesson was written down so it would not have to be learned twice",
        kind="memory",
        target="memory/incidents.md",
        action="write",
    )
    week.add(
        b + timedelta(minutes=124),
        s,
        "the daily report arrived without anyone asking for it",
        kind="cron",
        actor="system",
        target="daily-report",
        action="exec",
        minutes=1,
    )
    week.turn(b + timedelta(minutes=130), s, 0.023, 8800, 640)


def thursday(week: Week) -> None:
    s = "s-thu"
    b = MONDAY + timedelta(days=3, minutes=4)

    week.run(b, s, API, "git log showed the week in reverse, and the week was mostly locks", minutes=1)
    week.read(b + timedelta(minutes=5), s, f"{API}/src/queue.py", "queue.py was read again for the retry path")
    week.edit(b + timedelta(minutes=11), s, f"{API}/src/queue.py", "the retry path was split in two so each half could fail alone")
    week.run(
        b + timedelta(minutes=20),
        s,
        API,
        "the split retry failed the same way the unsplit one had",
        ok=False,
        error=LOCK,
    )
    week.edit(b + timedelta(minutes=26), s, f"{API}/src/queue.py", "the retry was put behind the lock it needed")
    week.run(b + timedelta(minutes=34), s, API, "the suite passed with the retry in place", minutes=3)
    week.turn(b + timedelta(minutes=42), s, 0.029, 11200, 820)

    week.add(
        b + timedelta(minutes=58),
        s,
        "a skill was written for the next person who meets this lock",
        kind="skill",
        target="skills/lock-debugging/SKILL.md",
        action="write",
    )
    week.fetch(b + timedelta(minutes=70), s, "https://docs.sqlalchemy.org/en/20/orm/session_transaction.html", "the SQLAlchemy docs were fetched and read for the transaction boundary")
    week.edit(b + timedelta(minutes=78), s, f"{API}/docs/locks.md", "the notes grew a section on renewing instead of extending")
    week.turn(b + timedelta(minutes=86), s, 0.017, 6900, 470)

    w = "s-thu-web"
    week.read(b + timedelta(minutes=130), w, f"{WEB}/src/api/client.ts", "the client was read before it was trusted")
    week.edit(b + timedelta(minutes=136), w, f"{WEB}/src/api/client.ts", "the client was given a backoff and a ceiling")
    week.run(b + timedelta(minutes=144), w, WEB, "the web suite passed with the retry in it", minutes=2)
    week.turn(b + timedelta(minutes=150), w, 0.014, 5600, 380)


def friday(week: Week) -> None:
    s = "s-fri"
    b = MONDAY + timedelta(days=4, minutes=6)

    week.run(b, s, API, "the full suite ran and held, all of it", minutes=5)
    week.run(b + timedelta(minutes=10), s, API, "the linter had one opinion about line length", minutes=1)
    week.edit(b + timedelta(minutes=13), s, f"{API}/docs/locks.md", "the long line was broken, and the opinion withdrawn")
    week.write(b + timedelta(minutes=18), s, f"{API}/CHANGELOG.md", "the changelog was written for people, not for git")
    week.turn(b + timedelta(minutes=24), s, 0.022, 8300, 590)

    week.run(b + timedelta(minutes=38), s, OPS, "terraform plan for production was short and dull", minutes=2)
    week.approval(b + timedelta(minutes=47), s, "infrastructure_apply", "once")
    week.run(b + timedelta(minutes=52), s, OPS, "atlas api went to production and stayed there", minutes=7)
    week.run(b + timedelta(minutes=64), s, OPS, "the production health check answered first time", minutes=1)
    week.turn(b + timedelta(minutes=70), s, 0.020, 7800, 560)

    week.message(b + timedelta(minutes=80), s, "standup", '"Shipped the lock fix and the retry split. Production is up. The invoice review is still open, and I have asked for a rollback decision on the queue worker."')
    week.write(b + timedelta(minutes=90), s, f"{API}/TODO.md", "next week was written down as four lines, not a paragraph")
    week.edit(b + timedelta(minutes=97), s, f"{API}/TODO.md", "the lock item was struck out, since it was done")
    week.read(b + timedelta(minutes=103), s, f"{API}/TODO.md", "the list was read back and found to be honest")
    week.add(
        b + timedelta(minutes=110),
        s,
        "a rollback was requested for the queue worker and left waiting",
        kind="approval",
        actor="human",
        action="approve",
        outcome="pending",
        target="production_rollback",
    )
    week.turn(b + timedelta(minutes=118), s, 0.016, 6400, 450)


def build() -> list[dict]:
    week = Week()
    monday(week)
    tuesday(week)
    wednesday(week)
    thursday(week)
    friday(week)

    for index, row in enumerate(week.rows, start=1):
        material = f"{row['session_id']}|{row['ts_utc']}|{row.get('tool')}|{index}"
        row["event_id"] = hashlib.sha1(material.encode()).hexdigest()
    return week.rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / ".demo-profile"))
    args = parser.parse_args()

    out = Path(args.out)
    data = out / "plugin-data" / "imprint"
    data.mkdir(parents=True, exist_ok=True)
    db_path = data / "data.db"
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()

    conn = db.connect(db_path)
    rows = build()
    for row in rows:
        db.insert_event(conn, row)
    conn.close()

    (out / "week.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"{len(rows)} events -> {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
