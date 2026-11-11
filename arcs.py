"""Deterministic arc extraction.

No model runs here. A ledger in, quests and chapters out, and the same ledger
always gives the same answer. That property is the whole reason the book can
be trusted: the *shape* of the week is computed, only the prose is generated.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

GAP_MINUTES = 90
FAIL_STREAK = 3
MOTIF_THRESHOLD = 3

TURNING_POINTS = (
    "the breakthrough",
    "the dead end",
    "the rescue",
    "the detour",
    "the hand-off",
)

# Stakes decide chapter order, never quality. Weights are a product decision:
# touching more files and retrying more times is more work than sitting still.
WEIGHT_FILES = 2.0
WEIGHT_RETRY = 1.5
WEIGHT_HOUR = 1.0
WEIGHT_COST = 5.0

_CHECK_HINTS = ("test", "pytest", "check", "lint", "build", "ci", "validate", "doctor")


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def load_events(conn, week: str | None = None) -> list[dict]:
    """Every event for a week, oldest first. ``week`` is ``2026-W45``."""
    sql = "SELECT * FROM events"
    params: tuple = ()
    if week:
        start, end = week_bounds(week)
        sql += " WHERE ts_utc >= ? AND ts_utc < ?"
        params = (start, end)
    sql += " ORDER BY ts_utc, id"

    rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def week_bounds(week: str) -> tuple[str, str]:
    year_text, week_text = week.split("-W")
    start = datetime.fromisocalendar(int(year_text), int(week_text), 1)
    return start.isoformat(), (start + timedelta(days=7)).isoformat()


# --------------------------------------------------------------------------
# quests
# --------------------------------------------------------------------------


def project_of(event: dict) -> str:
    """The project a row belongs to, or "" when it names none.

    Only absolute paths and git remotes count. A relative target such as
    ``skills/x/SKILL.md`` or an approval category is not a project: the caller
    inherits the session's project instead.
    """
    target = (event.get("target") or "").replace("\\", "/")

    if "github.com/" in target:
        tail = target.split("github.com/", 1)[1].split()[0].strip("/")
        parts = [part for part in tail.split("/") if part]
        if len(parts) >= 2:
            return f"github.com/{parts[0]}/{parts[1]}"

    if target.startswith(("/", "C:/", "c:/", "D:/", "d:/")):
        parts = [part for part in target.split("/") if part]
        if len(parts) >= 3:
            return "/".join(parts[:3])
        if len(parts) == 2 and parts[0].endswith(":"):
            return "/".join(parts)

    return ""


def quest_key(event: dict) -> str:
    return project_of(event) or event.get("session_id") or "unassigned"


def split_quests(events: Iterable[dict], gap_minutes: int = GAP_MINUTES) -> list[list[dict]]:
    """Split a week into quests: one per project, cut where work went quiet.

    Events are grouped by project first, then split on a silence longer than
    ``gap_minutes``. Grouping first is what keeps a week of interleaved
    projects from becoming a dozen one-line chapters: a project is a thread in
    the book, and the thread is followed across the days it was worked on.

    An approval, a cron run or a delegation often has no path in its target.
    Those inherit the project of the session they interrupted.
    """
    ordered = sorted(events, key=lambda event: event.get("ts_utc") or "")

    last_project: dict[str, str] = {}
    buckets: dict[str, list[dict]] = {}

    for event in ordered:
        session = event.get("session_id") or ""
        project = project_of(event)
        if project:
            last_project[session] = project

        key = project or last_project.get(session) or session or "unassigned"
        buckets.setdefault(key, []).append(event)

    quests: list[list[dict]] = []
    for rows in buckets.values():
        current: list[dict] = []
        last_ts: datetime | None = None
        for event in rows:
            when = _parse(event.get("ts_utc"))
            if current and when and last_ts and when - last_ts > timedelta(minutes=gap_minutes):
                quests.append(current)
                current = []
            current.append(event)
            last_ts = when or last_ts
        if current:
            quests.append(current)

    quests.sort(key=lambda quest: quest[0].get("ts_utc") or "")
    return quests


def quest_key_of(quest: list[dict]) -> str:
    """The project a quest belongs to, preferring a real path."""
    for event in quest:
        project = project_of(event)
        if project:
            return project
    return (quest[0].get("session_id") if quest else "") or "unassigned"


def quest_summary(quest: list[dict]) -> dict:
    """The row that goes in the ``quests`` table."""
    key = quest_key_of(quest)
    label = _quest_label(quest)
    return {
        "key": key,
        "label": label,
        "first_ts": quest[0]["ts_utc"],
        "last_ts": quest[-1]["ts_utc"],
        "stakes": round(stakes(quest), 3),
        "status": quest_status(quest),
    }


def _looks_like_session(text: str) -> bool:
    lowered = (text or "").lower()
    return lowered.startswith(("sess", "s-", "s_", "cron", "sub-"))


def _quest_label(quest: list[dict]) -> str:
    """A name a reader can follow: the project, or what the work touched."""
    if not quest:
        return "unfiled work"

    key = quest_key_of(quest)
    if _looks_like_session(key):
        for event in quest:
            target = (event.get("target") or "").replace("\\", "/").strip("/")
            tail = target.rsplit("/", 1)[-1]
            if tail and not _looks_like_session(tail):
                return tail.replace("-", " ").replace("_", " ")
        weekday = _parse(quest[0].get("ts_utc"))
        if weekday:
            return weekday.strftime("%A")
        return "unfiled work"

    name = key.rsplit("/", 1)[-1] or key
    if key.startswith("http"):
        name = key.split("//", 1)[-1].split("/", 1)[0]
    return name.replace("-", " ").replace("_", " ")


def quest_status(quest: list[dict]) -> str:
    """open | done | stalled."""
    if not quest:
        return "open"
    if unresolved(quest):
        return "stalled"
    return "done"


def unresolved(quest: list[dict]) -> bool:
    """An open thread: the quest ends badly, or a todo was never closed."""
    if not quest:
        return False

    meaningful = [event for event in quest if event.get("kind") != "llm"]
    if meaningful and meaningful[-1].get("outcome") in {"fail", "blocked", "pending"}:
        return True

    wrote_todo = any(
        event.get("action") == "write" and "todo" in (event.get("target") or "").lower()
        for event in quest
    )
    closed_todo = any(
        "todo" in (event.get("target") or "").lower()
        and event.get("outcome") == "ok"
        and event.get("action") == "write"
        and event is not quest[-1]
        for event in quest
    )
    return wrote_todo and not closed_todo


def stakes(quest: list[dict]) -> float:
    """Files touched, retries, wall-clock hours and spend, weighted."""
    files = {event.get("target") for event in quest if event.get("action") == "write"}
    retries = sum(1 for event in quest if event.get("outcome") == "fail")
    cost = sum(float(event.get("cost_usd") or 0.0) for event in quest)

    first = _parse(quest[0]["ts_utc"]) if quest else None
    last = _parse(quest[-1]["ts_utc"]) if quest else None
    hours = ((last - first).total_seconds() / 3600.0) if first and last else 0.0

    return (
        WEIGHT_FILES * len(files)
        + WEIGHT_RETRY * retries
        + WEIGHT_HOUR * hours
        + WEIGHT_COST * cost
    )


# --------------------------------------------------------------------------
# chapters
# --------------------------------------------------------------------------


def act_breaks(quest: list[dict]) -> list[int]:
    """Indices where a new chapter starts. Index 0 always starts a chapter."""
    if len(quest) < 2:
        return [0] if quest else []

    breaks: set[int] = {0}
    failures = 0
    last_failed_target: str | None = None
    last_failed_tool: str | None = None
    blocked_run = 0

    for index, event in enumerate(quest):
        outcome = event.get("outcome")
        target = event.get("target") or ""
        tool = event.get("tool") or ""

        if outcome == "blocked":
            blocked_run += 1
        elif outcome == "ok" and blocked_run >= 2 and event.get("kind") == "approval":
            breaks.add(index)
            blocked_run = 0
        elif outcome != "blocked":
            blocked_run = 0

        if outcome == "fail":
            if target and target == last_failed_target:
                failures += 1
            else:
                failures = 1
                last_failed_target = target
            last_failed_tool = tool
            continue

        if outcome == "ok":
            # Rule 1: three or more failures on one target, then a success.
            if failures >= FAIL_STREAK and target == last_failed_target:
                breaks.add(max(0, index - failures))

            # Rule 2: a check/test flipping from fail to ok on the same command.
            if _is_check(tool, target) and failures >= 1:
                breaks.add(index)

            # Rule 4: a different tool on the same target after a failure streak.
            if failures >= 2 and target == last_failed_target and tool != last_failed_tool:
                breaks.add(index)

            failures = 0
            last_failed_target = None
            last_failed_tool = None

    return sorted(breaks)


def build_chapters(quest: list[dict]) -> list[dict]:
    """One quest in, its chapters out, each with a fixed-vocabulary label."""
    if not quest:
        return []

    starts = act_breaks(quest)
    starts.append(len(quest))
    chapters: list[dict] = []

    for start, end in zip(starts, starts[1:]):
        chunk = quest[start:end]
        if not chunk:
            continue

        label = turning_point(chunk)
        # Two chapters with the same turning point in one quest are one
        # chapter: a book should not repeat a title, and the reader would
        # rather have the stronger, longer chapter.
        if chapters and chapters[-1]["label"] == label:
            chapters[-1]["events"].extend(chunk)
            chapters[-1]["stakes"] = round(stakes(chapters[-1]["events"]), 3)
            chapters[-1]["status"] = quest_status(chapters[-1]["events"])
            continue

        chapters.append(
            {
                "ordinal": len(chapters) + 1,
                "label": label,
                "events": chunk,
                "stakes": round(stakes(chunk), 3),
                "status": quest_status(chunk),
            }
        )

    return chapters


def turning_point(chunk: list[dict]) -> str:
    """Map a chapter to the fixed vocabulary. Never invents a label."""
    if any(event.get("kind") == "approval" for event in chunk):
        return "the rescue"
    if any(event.get("action") == "delegate" or event.get("subagent_id") for event in chunk):
        return "the hand-off"

    ended_ok = bool(chunk) and chunk[-1].get("outcome") == "ok"

    # A struggle that ends well is the breakthrough, whatever else it contains.
    if _has_failure_streak(chunk) and ended_ok:
        return "the breakthrough"

    tools = [event.get("tool") for event in chunk if event.get("tool")]
    if len(set(tools)) > 1 and _has_failure_streak(chunk):
        return "the detour"

    if chunk and chunk[-1].get("outcome") in {"fail", "blocked", "pending"}:
        return "the dead end"

    return "the breakthrough" if ended_ok else "the dead end"


def _has_failure_streak(chunk: list[dict]) -> bool:
    run = 0
    for event in chunk:
        if event.get("outcome") == "fail":
            run += 1
            if run >= 2:
                return True
        else:
            run = 0
    return False


def _is_check(tool: str, target: str) -> bool:
    haystack = f"{tool} {target}".lower()
    return any(hint in haystack for hint in _CHECK_HINTS)


# --------------------------------------------------------------------------
# motifs
# --------------------------------------------------------------------------


def motifs(events: Iterable[dict], threshold: int = MOTIF_THRESHOLD) -> list[dict]:
    """An error signature that recurs across the week."""
    counts: dict[str, dict] = {}

    for event in events:
        signature = event.get("error_sig")
        if not signature:
            continue
        entry = counts.setdefault(
            signature, {"signature": signature, "count": 0, "first_ts": event.get("ts_utc")}
        )
        entry["count"] += 1
        entry["last_ts"] = event.get("ts_utc")

    return [
        entry
        for entry in sorted(counts.values(), key=lambda item: -item["count"])
        if entry["count"] >= threshold
    ]


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
