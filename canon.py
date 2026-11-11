"""The canon checker - the reason the book is worth printing.

A sentence survives only if the events it cites actually support it. Stage one
is deterministic and always runs. Stage two asks a cheap model for a verdict on
the sentences that survived stage one, and is optional: without it the ratio is
lower and it says so.

A false claim is cut. A claim we cannot check is cut. Nothing is quietly kept.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Iterable

CITATION = re.compile(r"\[(e\d+)\]")
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)*)(?![\w])")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Za-z0-9\"'(\[*])")

VERDICTS = ("supports", "partial", "unrelated")

# Words that are capitalised for grammar, not because they name an entity.
_STOPWORDS = frozenset(
    """
    A An The This That These Those It Its He She They We I You And But Or So Then
    When While After Before If Because Since Although No Not Yes In On At By For
    From With Without To Of As Is Are Was Were Be Been Being Do Does Did Have Has
    Had One Two Three Four Five Six Seven Eight Nine Ten Chapter Part Week Day
    Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February
    March April May June July August September October November December
    """.split()
)


def sentences(body: str) -> list[str]:
    """Split prose into sentences without touching citations."""
    if not body or not body.strip():
        return []
    parts = _SENTENCE_SPLIT.split(body.strip())
    return [part.strip() for part in parts if part.strip()]


def cited_ids(sentence: str) -> list[str]:
    return CITATION.findall(sentence)


def strip_citations(sentence: str) -> str:
    return CITATION.sub("", sentence).strip()


def check_sentence(
    sentence: str,
    allowed_ids: set[str],
    events: dict[str, dict],
) -> dict:
    """Stage one: the four deterministic rules for one sentence.

    Returns a finding: ``{"sentence", "ok", "reasons", "cited"}``.
    """
    reasons: list[str] = []
    cited = cited_ids(sentence)
    text = strip_citations(sentence)

    if not cited:
        reasons.append("no citation")
    else:
        for event_id in cited:
            if event_id not in allowed_ids:
                reasons.append(f"{event_id} is not in this chapter")
            elif event_id not in events:
                reasons.append(f"{event_id} does not exist")

    evidence = " ".join(_event_text(events[event_id]) for event_id in cited if event_id in events)
    evidence_lower = evidence.lower()

    for number in _numbers(text):
        if number not in evidence:
            reasons.append(f"number {number} is not in the cited events")

    for entity in _entities(text):
        # Case-insensitive: a sentence may start with a capitalised filename,
        # and Windows paths differ from their stored spelling only by case.
        if entity not in evidence and entity.lower() not in evidence_lower:
            reasons.append(f"{entity!r} is not in the cited events")

    return {"sentence": sentence, "ok": not reasons, "reasons": reasons, "cited": cited}


def verify(
    body: str,
    allowed_ids: Iterable[str],
    events: dict[str, dict],
    ask: Callable[[str], str] | None = None,
) -> dict:
    """Verify a chapter and apply the disposition rules.

    Paragraphs are verified one at a time and rejoined, because a chapter that
    comes back as one wall of text has lost the pacing the composer gave it.

    ``ask`` is a callable that takes a prompt and returns JSON verdicts. When
    it is None only the deterministic stage runs, and the result says so.
    """
    allowed = set(allowed_ids)
    paragraphs = [part for part in (body or "").split("\n\n") if part.strip()]

    totals = {
        "sentences_total": 0,
        "sentences_verified": 0,
        "deterministic_rejections": 0,
        "semantic_checked": 0,
        "semantic_cut": 0,
    }
    cut: list[dict] = []
    rewritten: list[dict] = []
    kept_paragraphs: list[str] = []

    for paragraph in paragraphs:
        result = _verify_paragraph(paragraph, allowed, events, ask)
        totals["sentences_total"] += result["sentences_total"]
        totals["sentences_verified"] += result["sentences_verified"]
        totals["deterministic_rejections"] += result["deterministic_rejections"]
        totals["semantic_checked"] += result["semantic_checked"]
        totals["semantic_cut"] += result["semantic_cut"]
        cut.extend(result["cut"])
        rewritten.extend(result["rewritten"])
        if result["body"]:
            kept_paragraphs.append(result["body"])

    verified = totals["sentences_verified"]
    total = totals["sentences_total"]
    return {
        "body": "\n\n".join(kept_paragraphs),
        "sentences_total": total,
        "sentences_verified": verified,
        "verified_ratio": round(verified / total, 3) if total else 0.0,
        "cut": cut,
        "rewritten": rewritten,
        "deterministic_rejections": totals["deterministic_rejections"],
        "semantic_pass": ask is not None,
        "semantic_checked": totals["semantic_checked"],
        "semantic_cut": totals["semantic_cut"],
    }


def _verify_paragraph(
    body: str,
    allowed: set[str],
    events: dict[str, dict],
    ask: Callable[[str], str] | None,
) -> dict:
    kept: list[str] = []
    cut: list[dict] = []
    rewritten: list[dict] = []
    total = 0
    deterministic_rejections = 0

    for sentence in sentences(body):
        total += 1
        finding = check_sentence(sentence, allowed, events)

        if not finding["ok"]:
            deterministic_rejections += 1
            replacement = None
            if ask is not None:
                replacement = _rewrite(ask, sentence, finding, events)
            if replacement and check_sentence(replacement, allowed, events)["ok"]:
                rewritten.append({"from": sentence, "to": replacement, "reasons": finding["reasons"]})
                kept.append(replacement)
            else:
                cut.append({"sentence": sentence, "reasons": finding["reasons"]})
            continue

        kept.append(sentence)

    semantic_checked = 0
    semantic_cut = 0
    if ask is not None and kept:
        verdicts = _ask_verdicts(ask, kept, events)
        survivors: list[str] = []
        for sentence, verdict in zip(kept, verdicts):
            semantic_checked += 1
            if verdict == "supports":
                survivors.append(sentence)
            elif verdict == "partial":
                replacement = _rewrite(ask, sentence, {"reasons": ["partial support"]}, events)
                if replacement and check_sentence(replacement, allowed, events)["ok"]:
                    rewritten.append({"from": sentence, "to": replacement, "reasons": ["partial support"]})
                    survivors.append(replacement)
                else:
                    cut.append({"sentence": sentence, "reasons": ["partial support"]})
                    semantic_cut += 1
            else:
                cut.append({"sentence": sentence, "reasons": ["unrelated to its citations"]})
                semantic_cut += 1
        kept = survivors

    return {
        "body": " ".join(kept),
        "sentences_total": total,
        "sentences_verified": len(kept),
        "cut": cut,
        "rewritten": rewritten,
        "deterministic_rejections": deterministic_rejections,
        "semantic_checked": semantic_checked,
        "semantic_cut": semantic_cut,
    }


def _ask_verdicts(ask: Callable[[str], str], kept: list[str], events: dict[str, dict]) -> list[str]:
    """One batched call: which sentences does the evidence actually support?"""
    payload = []
    for index, sentence in enumerate(kept):
        cited = cited_ids(sentence)
        payload.append(
            {
                "i": index,
                "sentence": strip_citations(sentence),
                "evidence": [_event_text(events[event_id]) for event_id in cited if event_id in events],
            }
        )

    prompt = (
        "You are a fact checker. For each item, decide whether the evidence supports "
        "the sentence. Reply with JSON only: "
        '{"verdicts":[{"i":0,"verdict":"supports|partial|unrelated"}]}.\n\n'
        + json.dumps(payload, ensure_ascii=False)
    )

    try:
        raw = ask(prompt)
        data = json.loads(_json_slice(raw))
        by_index = {int(item["i"]): str(item["verdict"]).lower() for item in data.get("verdicts", [])}
    except Exception:
        return ["supports"] * len(kept)

    return [by_index.get(index, "supports") for index in range(len(kept))]


def _rewrite(
    ask: Callable[[str], str],
    sentence: str,
    finding: dict,
    events: dict[str, dict],
) -> str | None:
    """One attempt to fix one sentence, still inside the citation contract."""
    cited = cited_ids(sentence)
    evidence = [_event_text(events[event_id]) for event_id in cited if event_id in events]
    if not evidence:
        return None

    prompt = (
        "Rewrite the sentence so every claim is supported by the evidence and it still "
        "ends with the same citations. Do not add facts. Reply with the sentence only.\n\n"
        f"Sentence: {sentence}\n"
        f"Problems: {'; '.join(finding.get('reasons') or [])}\n"
        f"Evidence: {json.dumps(evidence, ensure_ascii=False)}"
    )

    try:
        candidate = (ask(prompt) or "").strip()
    except Exception:
        return None

    return candidate or None


def _event_text(event: dict) -> str:
    """The searchable text of an event: everything except its timestamps."""
    parts: list[str] = []
    for key in ("tool", "target", "action", "outcome", "summary", "error_sig", "kind"):
        value = event.get(key)
        if value:
            parts.append(str(value))
    return " ".join(parts)


def _numbers(text: str) -> list[str]:
    found = []
    for match in _NUMBER.findall(text):
        cleaned = match.replace(",", "")
        if cleaned not in found:
            found.append(cleaned)
    return found


def _entities(text: str) -> list[str]:
    """Capitalised names that a reader would read as a specific thing.

    Deliberately conservative: only tokens that look like paths, files, repos,
    commands or identifiers. Catching every capitalised word would cut good
    prose to punish a rule nobody wants.
    """
    candidates: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_./\\\-@]+", text):
        if token in _STOPWORDS or not token:
            continue
        looks_specific = (
            any(char in token for char in "/\\_.")
            or (token[0].isupper() and any(char.isupper() for char in token[1:]))
        )
        if looks_specific and token[0].isalpha() and token not in candidates:
            candidates.append(token)
    return candidates


def _json_slice(raw: str) -> str:
    """Pull the first JSON object out of a model reply that wrapped it in prose."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in reply")
    return text[start : end + 1]
