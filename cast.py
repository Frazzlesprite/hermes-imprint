"""The cast: who and what the week was made of.

Counts only. No model, no adjectives, no favourites.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

_URL_HOST = re.compile(r"https?://([^/\s:]+)")
_GITHUB = re.compile(r"github\.com/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)")
_MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_.\-]{1,38})")


def tools(events: Iterable[dict]) -> list[dict]:
    """Tools by call count, with their failure rate."""
    calls: Counter = Counter()
    failures: Counter = Counter()

    for event in events:
        name = event.get("tool")
        if not name or event.get("kind") != "tool":
            continue
        calls[name] += 1
        if event.get("outcome") == "fail":
            failures[name] += 1

    return [
        {
            "name": name,
            "count": count,
            "failures": failures[name],
            "failure_rate": round(failures[name] / count, 3) if count else 0.0,
        }
        for name, count in calls.most_common()
    ]


def paths(events: Iterable[dict]) -> list[dict]:
    """Project roots by touch count. Session ids are not places."""
    from .arcs import project_of

    touched: Counter = Counter()
    for event in events:
        target = event.get("target")
        if not target:
            continue
        key = project_of(event)
        if not key or key.startswith("sess") or key == "unassigned":
            continue
        touched[key] += 1

    return [{"name": name, "count": count} for name, count in touched.most_common()]


def repos(events: Iterable[dict]) -> list[dict]:
    """Git repositories by touch count."""
    touched: Counter = Counter()
    for event in events:
        match = _GITHUB.search(event.get("target") or "")
        if match:
            touched[match.group(1)] += 1

    return [{"name": name, "count": count} for name, count in touched.most_common()]


def services(events: Iterable[dict]) -> list[dict]:
    """Hosts called, by count."""
    touched: Counter = Counter()
    for event in events:
        match = _URL_HOST.search(event.get("target") or "")
        if match:
            touched[match.group(1).lower()] += 1

    return [{"name": name, "count": count} for name, count in touched.most_common()]


def people(events: Iterable[dict]) -> list[dict]:
    """Handles mentioned in message events.

    Only what is written down: an ``@handle`` in a message summary. Imprint
    never guesses that a name is a person.
    """
    touched: Counter = Counter()
    for event in events:
        if event.get("kind") != "message":
            continue
        for handle in _MENTION.findall(event.get("summary") or ""):
            touched[handle] += 1

    return [{"name": handle, "count": count} for handle, count in touched.most_common()]


def build(events: Iterable[dict]) -> dict:
    """The whole dramatis personae, ready for the page."""
    events = list(events)
    return {
        "people": people(events),
        "repos": repos(events),
        "paths": paths(events),
        "tools": tools(events),
        "services": services(events),
    }


def isEmpty(cast: dict) -> bool:
    """True when there is nobody and nothing to list."""
    return not any(cast.get(key) for key in ("people", "repos", "paths", "tools", "services"))
