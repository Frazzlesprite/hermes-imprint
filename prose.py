"""Constrained prose generation, and the offline composer.

Two paths produce a chapter:

* ``ctx.llm`` with the style contract below, when a model is configured.
* the offline composer, which builds prose from the ledger's structured fields.
  It is not a placeholder: it carries the register of the chosen genre, and
  every sentence still cites the event it came from.

Genres change voice and chapter titles only. They never change the event set.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_WORDS = 150
MAX_WORDS = 350

GENRES = {
    "epic": {
        "voice": (
            "Literary historical: grave, measured, third person, past tense. Long clauses "
            "that carry their weight at the end, concrete nouns, no archaisms, no exclamation "
            "marks, no second person, no moralising. Restraint over drama."
        ),
        "titles": "Noun phrases, four words or fewer, title case, no subtitle.",
        "label": "Epic",
    },
    "noir": {
        "voice": (
            "Neo-noir: contemporary, cool, first-person-absent. Short declarative sentences, "
            "dry observation, understatement. No pastiche, no gumshoe slang, no weather. "
            "The menace is in what is left out."
        ),
        "titles": "Short flat phrases, title case, faintly ominous.",
        "label": "Noir",
    },
    "ships-log": {
        "voice": (
            "Terse log entries. Plain statements of what ran, what held and what did not. "
            "No metaphor, no colour, no editorialising."
        ),
        "titles": "Plain descriptive phrases, lower case except the first word.",
        "label": "Ship's log",
    },
}

SYSTEM_PROMPT = """You write one chapter of a factual weekly book about software work.

Hard rules, no exceptions:
1. Every sentence ends with one or more citations in the form [e123].
2. Do not state a fact that is not in a cited event.
3. Every number in your prose must appear in a cited event's fields.
4. No dialogue unless it is quoted from a message event.
5. Between {min_words} and {max_words} words.
6. Do not moralise, do not compliment the user, do not explain the plugin or the book.

You are given the chapter's events as JSON lines. Each has an id. Cite the id
in square brackets at the end of the sentence it supports. If you cannot
support a sentence with an event, do not write the sentence.

Voice: {voice}
Chapter titles: {titles}

The register is the point. A reader should be able to tell the editions apart
with the facts unchanged.
"""

USER_PROMPT = """Week: {week}
Chapter {ordinal}: {label}
Quest: {quest}

Events:
{events}

Write the chapter body only. No heading, no preamble, no closing line.
"""


def chapter_title(genre: str, label: str, ordinal: int, quest_label: str) -> str:
    """Deterministic title. The chapter number is set by the page, not the title."""
    place = _titlecase(quest_label)
    if genre == "ships-log":
        return f"{quest_label} - {label}"
    if genre == "noir":
        return f"{label.title()}, {place}"
    return f"{place}, or {label.title()}"


_ACRONYMS = {"api", "cli", "db", "ci", "sql", "http", "pr", "ui", "id", "url"}


def _titlecase(text: str) -> str:
    words = []
    for word in (text or "").split():
        if word.lower() in _ACRONYMS:
            words.append(word.upper())
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def build_prompt(
    genre: str,
    chapter: dict,
    quest_label: str,
    week: str,
    event_rows: list[dict],
) -> list[dict]:
    """The two messages for one chapter."""
    style = GENRES.get(genre, GENRES["epic"])
    system = SYSTEM_PROMPT.format(
        min_words=MIN_WORDS,
        max_words=MAX_WORDS,
        voice=style["voice"],
        titles=style["titles"],
    )

    lines = []
    for row in event_rows:
        lines.append(
            json.dumps(
                {
                    "id": f"e{row['id']}",
                    "ts": row.get("ts_utc"),
                    "kind": row.get("kind"),
                    "tool": row.get("tool"),
                    "target": row.get("target"),
                    "action": row.get("action"),
                    "outcome": row.get("outcome"),
                    "summary": row.get("summary"),
                    "error": row.get("error_sig"),
                },
                ensure_ascii=False,
            )
        )

    user = USER_PROMPT.format(
        week=week,
        ordinal=chapter.get("ordinal", 1),
        label=chapter.get("label", ""),
        quest=quest_label,
        events="\n".join(lines),
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def write_chapter(
    llm,
    genre: str,
    chapter: dict,
    quest_label: str,
    week: str,
    event_rows: list[dict],
    cache_dir: Path | None = None,
) -> str:
    """Generate one chapter body, cached by its event set.

    With no model configured, the chapter is composed by ``offline_chapter``.
    That path is deterministic and cites every sentence; the colophon says
    which path produced the book.
    """
    if llm is None:
        return offline_chapter(genre, event_rows, quest_label)

    key = cache_key(genre, event_rows)
    if cache_dir is not None:
        cached = cache_dir / f"{key}.md"
        if cached.exists():
            return cached.read_text(encoding="utf-8")

    messages = build_prompt(genre, chapter, quest_label, week, event_rows)
    result = llm.complete(
        messages=messages,
        max_tokens=900,
        temperature=0.5,
        purpose="imprint.chapter",
    )
    body = (getattr(result, "text", "") or "").strip()

    if cache_dir is not None and body:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{key}.md").write_text(body, encoding="utf-8")

    return body


def cache_key(genre: str, event_rows: list[dict]) -> str:
    material = genre + "|" + "|".join(
        f"{row.get('id')}:{row.get('summary') or ''}:{row.get('outcome') or ''}"
        for row in event_rows
    )
    return hashlib.sha1(material.encode("utf-8", "replace")).hexdigest()[:16]


def word_count(body: str) -> int:
    return len((body or "").split())


# --------------------------------------------------------------------------
# offline composer
# --------------------------------------------------------------------------
#
# Clauses are built from structured fields - tool, target, outcome, kind - so
# they are grammatical whatever the capture wrote in ``summary``. Frames carry
# cadence; the facts stay in the clause and the citation.

_FRAMES = {
    "epic": {
        "open": (
            "{Clause}, and the work began there {ids}.",
            "{Clause}, at the start of it {ids}.",
            "{Clause} first, and the rest followed {ids}.",
        ),
        "ok": (
            "{Clause}, and the matter rested there {ids}.",
            "{Clause}, and nothing further was asked of it {ids}.",
            "{Clause}, which settled that {ids}.",
        ),
        "fail": (
            "{Clause}, and it was not a small thing {ids}.",
            "{Clause}, and the fault was left standing {ids}.",
            "{Clause}, to nobody's surprise {ids}.",
        ),
        "fail_many": (
            "Again and again the same ground: {clause} {ids}.",
            "{Clause}, repeated until it was plain {ids}.",
        ),
        "blocked": (
            "{Clause}, and the work was turned aside {ids}.",
            "{Clause}, before it could begin {ids}.",
        ),
        "turn": (
            "{Clause}, and the ground shifted {ids}.",
            "{Clause}, after which the rest went differently {ids}.",
        ),
        "approval": (
            "{Clause}, and the work went on {ids}.",
            "{Clause}, and that was enough {ids}.",
        ),
        "denied": (
            "{Clause}, and the work went around it {ids}.",
            "{Clause}, so the route changed {ids}.",
        ),
        "delegate": (
            "{Clause}, and it came back changed {ids}.",
            "{Clause}, and what returned was not what was sent {ids}.",
        ),
        "cron": (
            "{Clause}, unasked {ids}.",
            "{Clause}, whether or not anyone was watching {ids}.",
        ),
        "memory": (
            "{Clause} {ids}.",
            "{Clause}, kept against the next time {ids}.",
        ),
        "close": (
            "{Clause}, and it was left there {ids}.",
            "{Clause}, finished or not {ids}.",
        ),
    },
    "noir": {
        "open": (
            "{Clause}, and that was the start of it {ids}.",
            "{Clause}, and it went from there {ids}.",
        ),
        "ok": (
            "{Clause}, and nothing came of it {ids}.",
            "{Clause}, clean {ids}.",
            "{Clause}, no trouble {ids}.",
        ),
        "fail": (
            "{Clause}, and it did not take {ids}.",
            "{Clause}, same result {ids}.",
            "{Clause}, no luck {ids}.",
        ),
        "fail_many": (
            "{Clause}, again and again {ids}.",
            "Same wall, same answer: {clause} {ids}.",
        ),
        "blocked": (
            "{Clause}, so it was routed around {ids}.",
            "{Clause}, and that was that {ids}.",
        ),
        "turn": (
            "{Clause}, and that was the turn {ids}.",
            "{Clause}, and after that it moved {ids}.",
        ),
        "approval": (
            "{Clause}, and the work went on {ids}.",
            "{Clause}, once {ids}.",
        ),
        "denied": (
            "{Clause}, so the work went around it {ids}.",
            "{Clause}, the hard way then {ids}.",
        ),
        "delegate": (
            "{Clause}, and it came back heavier {ids}.",
            "{Clause}, somebody else's problem briefly {ids}.",
        ),
        "cron": (
            "{Clause}, unasked {ids}.",
            "{Clause}, on schedule {ids}.",
        ),
        "memory": (
            "{Clause}, for later {ids}.",
            "{Clause}, kept {ids}.",
        ),
        "close": (
            "{Clause}, and it was left there {ids}.",
            "{Clause}, and it ended there {ids}.",
        ),
    },
    "ships-log": {
        "open": ("{clause} - first of the day {ids}",),
        "ok": ("{clause} - confirmed {ids}", "{clause} - no fault {ids}"),
        "fail": ("{clause} - logged {ids}", "{clause} - no hold {ids}"),
        "fail_many": ("repeated failure on the same ground {ids}",),
        "blocked": ("{clause} - no clearance {ids}",),
        "turn": ("{clause} - after the change {ids}",),
        "approval": ("{clause} - by a person {ids}",),
        "denied": ("{clause} - work routed around it {ids}",),
        "delegate": ("{clause} - returned {ids}",),
        "cron": ("scheduled report delivered {ids}",),
        "memory": ("{clause} - for later {ids}",),
        "close": ("{clause} - log closed {ids}",),
    },
}

_TOOL_PHRASE = {
    "terminal": "the terminal run",
    "read_file": "the read",
    "write_file": "the write",
    "edit_file": "the edit",
    "web_search": "the search",
    "web_fetch": "the fetch",
    "git": "the git work",
}

# A plain declarative is the most narrative frame there is: with a human
# summary inside it, "the README described a queue that had once been
# reliable [e1]." needs nothing added.
for _table in _FRAMES.values():
    for _key in tuple(_table):
        if _key != "open":
            _table[_key] = ("{Clause} {ids}.",) + tuple(_table[_key])

_MACHINE_SUMMARY = re.compile(
    r"^(terminal|read_file|write_file|edit_file|web_search|web_fetch|git|shell|list_directory)\b",
    re.IGNORECASE,
)


def _human_summary(row: dict) -> str:
    """The summary, when it is a clause a person wrote rather than a log line."""
    text = str(row.get("summary") or "").strip().rstrip(".")
    if not text:
        return ""
    if _MACHINE_SUMMARY.match(text):
        return ""
    lowered = text.lower()
    if lowered.startswith(("approval requested", "approval once", "approval session", "approval deny")):
        return ""
    if " completed" in lowered and lowered.startswith(("the ", "a ")):
        return ""

    if text.startswith('"'):
        # A quoted message is dialogue, and reads best attributed. Internal
        # sentence breaks become em dashes: a citation can only close one
        # sentence, so a three-sentence quote would lose its first two.
        inner = text.strip().strip('"').rstrip(".")
        inner = re.sub(r"\.\s+", " - ", inner)
        return f'someone said "{inner}"'

    return text


def offline_chapter(genre: str, event_rows: list[dict], quest: str = "the work") -> str:
    """Compose a chapter from the ledger, in the genre's register."""
    frames = _FRAMES.get(genre, _FRAMES["epic"])
    beats = _beats(event_rows)

    if not beats:
        # A chapter of pure model turns still gets a line, and still cites.
        model_rows = [row for row in event_rows if row.get("kind") == "llm"]
        if model_rows:
            ids = " ".join(f"[e{row['id']}]" for row in model_rows)
            return f"The model was asked, and answered {ids}."
        return ""

    # Small runs of successes or failures become one sentence each, so a
    # chapter has rhythm instead of a single sentence carrying six events.
    plan: list[tuple[str, list[dict], bool]] = []
    for index, beat in enumerate(beats):
        rows = beat["rows"]
        if beat["kind"] in {"ok", "fail"} and 1 < len(rows) <= 3:
            for offset, row in enumerate(rows):
                plan.append((beat["kind"], [row], index == 0 and offset == 0))
        else:
            plan.append((beat["kind"], rows, index == 0))

    sentences: list[str] = []
    used_frames: set[str] = set()
    used_clauses: dict = {"clauses": set(), "verbs": set(), "subjects": set()}
    for index, (key, rows, first) in enumerate(plan):
        if index == 0:
            sentences.append(_opener(genre, rows, quest, used_clauses))
            continue

        frame_key = key
        if index == len(plan) - 1 and key == "ok" and len(plan) > 1:
            frame_key = "close"

        # Alternate plain and framed sentences: a tail on every sentence is
        # what makes prose sound like a report. A turn always gets its frame -
        # that sentence is the chapter's hinge.
        if index % 2 == 0 and key != "turn":
            sentences.append(_render(("{Clause} {ids}.",), rows, genre, used_clauses=used_clauses))
            continue

        frame = frames.get(frame_key) or frames["ok"]
        sentences.append(
            _render(frame, rows, genre, first=first, used_frames=used_frames, used_clauses=used_clauses)
        )

    return _paragraph(sentences)


def _opener(genre: str, rows: list[dict], quest: str, used_clauses: dict | None = None) -> str:
    """The first sentence names the day and the project, then the event."""
    ids = " ".join(f"[e{row['id']}]" for row in rows)
    clause = _clause(rows[-1], genre, ids, used_clauses)
    day = _weekday(rows[0])

    if genre == "ships-log":
        return _tidy(f"{day} {quest}: {clause} {ids}".strip())
    if genre == "noir":
        return _tidy(f"{day}, in {_titlecase(quest)}: {clause} {ids}".strip())
    return _tidy(f"On {day}, in {_titlecase(quest)}, {clause} {ids}".strip())


def _render(
    frame_variants,
    rows: list[dict],
    genre: str,
    first: bool = False,
    used_frames: set[str] | None = None,
    used_clauses: dict | None = None,
) -> str:
    ids = " ".join(f"[e{row['id']}]" for row in rows)
    variants = frame_variants if isinstance(frame_variants, tuple) else (frame_variants,)
    seed = int(hashlib.sha1(ids.encode("utf-8")).hexdigest()[:8], 16)
    frame = _pick_fresh(variants, seed, used_frames if used_frames is not None else set())

    clause = _clause(rows[-1], genre, ids, used_clauses)
    if '"' in clause:
        # Dialogue carries itself; a frame tail after a quote reads like a
        # caption under a photograph.
        frame = "{Clause} {ids}."
    text = frame.format(clause=clause, Clause=_cap(clause), ids=ids)

    if first and genre != "ships-log":
        day = _weekday(rows[0])
        if day:
            body = text
            if len(text) > 1 and text[1:2].islower():
                body = text[:1].lower() + text[1:]
            text = f"On {day}, {body}"

    return _tidy(text)


def _pick(options, seed: int):
    if not isinstance(options, (tuple, list)):
        options = (options,)
    return options[seed % len(options)]


def _pick_fresh(options, seed: int, used: set[str]):
    """Pick a variant the chapter has not used yet, then cycle."""
    if not isinstance(options, (tuple, list)):
        options = (options,)
    for offset in range(len(options)):
        candidate = options[(seed + offset) % len(options)]
        if candidate not in used:
            used.add(candidate)
            return candidate
    return options[seed % len(options)]


def _weekday(row: dict) -> str:
    value = row.get("ts_utc")
    if not value:
        return ""
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value)).strftime("%A")
    except ValueError:
        return ""


_ACTION_OF_TOOL = {
    "read_file": "read",
    "list_directory": "read",
    "write_file": "write",
    "edit_file": "edit",
    "apply_patch": "edit",
    "web_search": "search",
    "web_fetch": "fetch",
    "terminal": "exec",
    "shell": "exec",
}

_SUBJECTS = {
    "epic": {
        "read": ("the brief", "the page", "the note"),
        "write": ("the new file", "the change", "the write"),
        "edit": ("the change", "the patch", "the edit"),
        "exec": ("the command", "the run", "the suite"),
        "search": ("the search", "the question", "the index"),
        "fetch": ("the page", "the reference", "the fetch"),
        "approval": ("the request", "the permission", "the sign-off"),
        "delegate": ("the hand-off", "the work", "the second pair of hands"),
        "cron": ("the report", "the scheduled note"),
        "memory": ("the note", "the record"),
    },
    "noir": {
        "read": ("the brief", "the page", "the note"),
        "write": ("the write", "the new file", "the change"),
        "edit": ("the change", "the patch", "the edit"),
        "exec": ("the command", "the run", "the suite"),
        "search": ("the search", "the question", "the index"),
        "fetch": ("the page", "the fetch", "the reference"),
        "approval": ("the request", "the permission", "the sign-off"),
        "delegate": ("the job", "the work", "the hand-off"),
        "cron": ("the report", "the scheduled note"),
        "memory": ("the note", "the record"),
    },
    "ships-log": {
        "read": ("document", "file", "page"),
        "write": ("file", "output", "record"),
        "edit": ("patch", "file", "diff"),
        "exec": ("run", "command", "check"),
        "search": ("query", "search", "index"),
        "fetch": ("page", "fetch", "document"),
        "approval": ("approval", "request", "sign-off"),
        "delegate": ("task", "hand-off", "delegation"),
        "cron": ("scheduled report", "daily report"),
        "memory": ("note", "record"),
    },
}

_VERBS = {
    "epic": {
        ("read", "ok"): ("was read", "was read through", "gave up what it had"),
        ("read", "fail"): ("would not open", "would not give up its answer"),
        ("write", "ok"): ("was written", "was set down", "went to disk"),
        ("write", "fail"): ("would not take",),
        ("edit", "ok"): ("went in", "was made", "took the change"),
        ("edit", "fail"): ("would not take the change",),
        ("exec", "ok"): ("held", "went through", "came back clean"),
        ("exec", "fail"): ("did not hold", "broke", "came back with an error"),
        ("search", "ok"): ("went out", "was made", "came back full"),
        ("search", "fail"): ("came back empty",),
        ("fetch", "ok"): ("came back", "was fetched", "arrived intact"),
        ("fetch", "fail"): ("did not come back",),
        ("approval", "ok"): ("was granted", "was given", "was allowed"),
        ("approval", "fail"): ("was refused", "was not given"),
        ("delegate", "ok"): ("went out", "was handed on", "was passed along"),
        ("cron", "ok"): ("arrived unasked", "came in on its own"),
        ("memory", "ok"): ("was written down", "was kept"),
        ("blocked", "any"): ("never ran", "was turned aside", "stopped at the door"),
        ("pending", "any"): ("was left open", "was still waiting"),
    },
    "noir": {
        ("read", "ok"): ("got read", "was read", "said what it had to say"),
        ("read", "fail"): ("wouldn't open",),
        ("write", "ok"): ("went down", "landed", "was written"),
        ("write", "fail"): ("didn't take",),
        ("edit", "ok"): ("took", "went in", "landed"),
        ("edit", "fail"): ("didn't take",),
        ("exec", "ok"): ("held", "was fine", "went through"),
        ("exec", "fail"): ("didn't take", "came back wrong", "stopped"),
        ("search", "ok"): ("went out", "came back with something", "turned something up"),
        ("search", "fail"): ("came back empty",),
        ("fetch", "ok"): ("came back", "arrived"),
        ("fetch", "fail"): ("came back empty",),
        ("approval", "ok"): ("came back yes", "was granted"),
        ("approval", "fail"): ("came back no", "was refused"),
        ("delegate", "ok"): ("went out", "was handed on"),
        ("cron", "ok"): ("turned up", "showed up"),
        ("memory", "ok"): ("got written down", "was kept"),
        ("blocked", "any"): ("never ran", "stopped at the door"),
        ("pending", "any"): ("stayed open", "was left hanging"),
    },
    "ships-log": {
        ("read", "ok"): ("read", "read through", "opened"),
        ("read", "fail"): ("unreadable", "would not open"),
        ("write", "ok"): ("written", "saved", "committed"),
        ("write", "fail"): ("write failed",),
        ("edit", "ok"): ("changed", "edited", "applied"),
        ("edit", "fail"): ("edit failed",),
        ("exec", "ok"): ("held", "passed", "clean"),
        ("exec", "fail"): ("failed", "errored", "stopped"),
        ("search", "ok"): ("returned", "answered", "came back full"),
        ("search", "fail"): ("returned nothing", "came back empty"),
        ("fetch", "ok"): ("fetched", "retrieved", "returned"),
        ("fetch", "fail"): ("failed", "came back empty"),
        ("approval", "ok"): ("granted", "signed off", "allowed"),
        ("approval", "fail"): ("refused", "denied"),
        ("delegate", "ok"): ("delegated", "handed off"),
        ("cron", "ok"): ("delivered", "delivered on schedule"),
        ("memory", "ok"): ("noted", "recorded"),
        ("blocked", "any"): ("stopped", "blocked"),
        ("pending", "any"): ("open", "waiting"),
    },
}


def _action_bucket(row: dict) -> str:
    tool = str(row.get("tool") or "")
    return _ACTION_OF_TOOL.get(tool, "exec")


def _clause(row: dict, genre: str, unique: str, used: dict | None = None) -> str:
    """Compose a clause from the event's fields, in the genre's own words.

    The ledger's summary is evidence, not prose: it stays in the appendix. What
    the sentence says is decided here, from tool, action and outcome, so epic
    and noir cannot end up sharing a sentence. Within a chapter, a subject, a
    verb and a clause are each used once before any is repeated.
    """
    seed = int(hashlib.sha1(unique.encode("utf-8")).hexdigest()[:8], 16)
    style = genre if genre in _SUBJECTS else "epic"

    kind = str(row.get("kind") or "tool")
    outcome = str(row.get("outcome") or "ok")

    if kind == "approval":
        bucket, ok = "approval", outcome != "blocked"
    elif kind == "cron":
        bucket, ok = "cron", True
    elif kind in {"memory", "skill"}:
        bucket, ok = "memory", True
    elif row.get("action") == "delegate":
        bucket, ok = "delegate", outcome not in {"fail", "blocked"}
    else:
        bucket, ok = _action_bucket(row), outcome not in {"fail", "blocked"}

    if outcome == "blocked":
        key = ("blocked", "any")
    elif outcome == "pending":
        key = ("pending", "any")
    else:
        key = (bucket, "ok" if ok else "fail")

    verbs = _VERBS[style].get(key) or _VERBS[style][("exec", "ok")]
    subjects = _SUBJECTS[style][bucket]

    if used is None:
        used = {"clauses": set(), "verbs": set(), "subjects": set()}
    used.setdefault("clauses", set())
    used.setdefault("verbs", set())
    used.setdefault("subjects", set())

    clause = ""
    for relax in range(4):
        for subject_index in range(len(subjects)):
            for verb_index in range(len(verbs)):
                subject = subjects[(seed + subject_index) % len(subjects)]
                verb = verbs[((seed >> 5) + verb_index) % len(verbs)]
                candidate = f"{subject} {verb}"
                if candidate in used["clauses"]:
                    continue
                if relax < 2 and verb in used["verbs"] and len(used["verbs"]) < len(verbs):
                    continue
                if relax < 1 and subject in used["subjects"] and len(used["subjects"]) < len(subjects):
                    continue
                used["clauses"].add(candidate)
                used["verbs"].add(verb)
                used["subjects"].add(subject)
                return candidate

    return clause or f"{subjects[0]} {verbs[0]}"


def _beats(rows: list[dict]) -> list[dict]:
    """Group consecutive events into beats a sentence can carry."""
    beats: list[dict] = []
    pending_approval: dict | None = None

    for row in rows:
        kind = str(row.get("kind") or "tool")

        if kind == "llm":
            continue

        if kind == "approval":
            if pending_approval is None and row.get("outcome") == "pending":
                pending_approval = row
                continue
            decision = row
            outcome = "denied" if decision.get("outcome") == "blocked" else "approval"
            beats.append({"kind": outcome, "rows": [pending_approval or decision, decision]})
            pending_approval = None
            continue

        if kind == "cron":
            beats.append({"kind": "cron", "rows": [row]})
            continue

        if kind in {"memory", "skill"}:
            beats.append({"kind": "memory", "rows": [row]})
            continue

        if row.get("action") == "delegate":
            if beats and beats[-1]["kind"] == "delegate":
                beats[-1]["rows"].append(row)
            else:
                beats.append({"kind": "delegate", "rows": [row]})
            continue

        action_kind = _action_kind(row)
        if (
            beats
            and beats[-1]["kind"] == action_kind
            and action_kind in {"fail", "ok"}
            and len(beats[-1]["rows"]) < 3
        ):
            beats[-1]["rows"].append(row)
            if len(beats[-1]["rows"]) >= 3 and action_kind == "fail":
                beats[-1]["kind"] = "fail_many"
        else:
            beats.append({"kind": action_kind, "rows": [row]})

    if pending_approval is not None:
        beats.append({"kind": "approval", "rows": [pending_approval]})

    # A failure streak that ends in a success is the chapter's turn.
    for index in range(len(beats) - 1):
        if beats[index]["kind"] in {"fail", "fail_many"} and beats[index + 1]["kind"] == "ok":
            beats[index + 1]["kind"] = "turn"

    return _trim(beats)


def _action_kind(row: dict) -> str:
    outcome = str(row.get("outcome") or "ok")
    if outcome == "fail":
        return "fail"
    if outcome == "blocked":
        return "blocked"
    if outcome == "pending":
        return "fail"
    return "ok"


def _trim(beats: list[dict], limit: int = 8) -> list[dict]:
    """Keep the first three and last four beats; fold the middle together."""
    if len(beats) <= limit:
        return beats

    head = beats[:3]
    middle = beats[3:-4]
    tail = beats[-4:]
    folded_rows = [row for beat in middle for row in beat["rows"]]
    return head + [{"kind": _dominant_kind(middle), "rows": folded_rows}] + tail


def _dominant_kind(beats: list[dict]) -> str:
    counts: dict[str, int] = {}
    for beat in beats:
        counts[beat["kind"]] = counts.get(beat["kind"], 0) + 1
    return max(counts, key=lambda key: counts[key]) if counts else "ok"


def _paragraph(sentences: list[str]) -> str:
    """Break into paragraphs of three or four sentences."""
    if len(sentences) <= 3:
        return " ".join(sentences)

    paragraphs = [sentences[index : index + 3] for index in range(0, len(sentences), 3)]
    return "\n\n".join(" ".join(paragraph) for paragraph in paragraphs)


def _tidy(text: str) -> str:
    out = text.replace(" .", ".").replace("  ", " ").strip()
    if out and out[-1] not in ".!?":
        out += "."
    return out


def _roman(number: int) -> str:
    numerals = (
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    result = []
    remainder = max(1, int(number))
    for value, glyph in numerals:
        while remainder >= value:
            result.append(glyph)
            remainder -= value
    return "".join(result)
