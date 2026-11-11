"""Secret and PII scrubbing, applied before anything is written.

Raw tool payloads never reach the ledger. What lands is a short summary that
has already been through here, so a leaked key cannot survive in the book,
the appendix, or a compiled PDF. Everything in this module is pure: no I/O,
no clock, no imports from Hermes.
"""

from __future__ import annotations

import fnmatch
import re

REDACTED = "[redacted]"
SUMMARY_LIMIT = 280

# Ordered: the first pattern to match claims the span. Long, unambiguous token
# shapes come before the looser "key = value" catch-all.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"
        ),
    ),
    (
        "bearer",
        re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._\-=+/]{12,})"),
    ),
    (
        "assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|secret|token|password|passwd|pwd)"
            r"\s*[:=]\s*[\"']?([^\s\"'&,;]{6,})"
        ),
    ),
    (
        "url_credentials",
        re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"),
    ),
)

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("phone", re.compile(r"\+\d{10,15}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
)

# Paths and identifiers that make two instances of the same error look alike.
_ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_WIN_PATH = re.compile(r"[A-Za-z]:\\(?:[^\\\s\"']+\\)*[^\\\s\"']*")
_POSIX_PATH = re.compile(r"(?<![\w.])/(?:[\w.\-]+/)+[\w.\-]*")
_HEX_ID = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")
_WHITESPACE = re.compile(r"\s+")

_SIGNATURE_LIMIT = 120


def redact(text: str) -> tuple[str, tuple[str, ...]]:
    """Replace secrets and identifiers in ``text``.

    Returns the cleaned string and the sorted kinds that were hit, so the
    caller can record *that* a redaction happened without recording what it
    was.
    """
    if not text:
        return "", ()

    kinds: set[str] = set()
    cleaned = text

    for kind, pattern in _SECRET_PATTERNS:
        if pattern.search(cleaned):
            cleaned = pattern.sub(REDACTED, cleaned)
            kinds.add(kind)

    for kind, pattern in _PII_PATTERNS:
        if pattern.search(cleaned):
            cleaned = pattern.sub(REDACTED, cleaned)
            kinds.add(kind)

    return cleaned, tuple(sorted(kinds))


def summarize(text: str, limit: int = SUMMARY_LIMIT) -> tuple[str, tuple[str, ...]]:
    """Collapse, redact and bound one line of evidence.

    The limit counts characters of the *cleaned* text: truncation happens
    after redaction so a cut can never expose half a key.
    """
    cleaned, kinds = redact(_WHITESPACE.sub(" ", (text or "").strip()))

    if len(cleaned) > limit:
        clipped = cleaned[: limit - 1]
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        cleaned = clipped + "\u2026"

    return cleaned, kinds


def error_signature(text: str) -> str:
    """A stable fingerprint for an error, used for motif detection.

    Two runs of the same failure produce the same signature; the volatile
    parts (paths, pids, timestamps, numbers) do not.
    """
    if not text:
        return ""

    signature = str(text)
    signature = _UUID.sub("<id>", signature)
    signature = _ISO_TS.sub("<ts>", signature)
    signature = _WIN_PATH.sub("<path>", signature)
    signature = _POSIX_PATH.sub("<path>", signature)
    signature = _HEX_ID.sub("<id>", signature)
    signature = _NUMBER.sub("N", signature)
    signature = _WHITESPACE.sub(" ", signature).strip()

    if len(signature) > _SIGNATURE_LIMIT:
        signature = signature[: _SIGNATURE_LIMIT - 1].rstrip() + "\u2026"

    return signature


def normalize_target(target: str) -> str:
    """Normalise a path or repo target for storage and comparison."""
    if not target:
        return ""
    return target.replace("\\", "/").rstrip("/")


def is_excluded(target: str, patterns: list[str] | tuple[str, ...]) -> bool:
    """True when ``target`` falls under any exclusion pattern.

    Matching is case-insensitive on normalised separators, because the demo
    machine is Windows and ``C:\\Code`` is the same place as ``c:/code``.
    """
    if not target or not patterns:
        return False

    candidate = normalize_target(target).lower()
    for raw in patterns:
        pattern = normalize_target(str(raw)).lower()
        if not pattern:
            continue
        if fnmatch.fnmatch(candidate, pattern):
            return True
        if candidate == pattern or candidate.startswith(pattern + "/"):
            return True

    return False
