"""Hooks in, ledger rows out.

This module is the only place that reacts to a live session. It is deliberately
dull: hash the arguments, normalise the target, redact the summary, write one
row. Payload shapes are read defensively because Hermes adds fields additively
and the spec is a snapshot, not the contract.

Rules this file exists to keep:

* a tool's arguments are hashed, never stored;
* a replay of the same hook cannot duplicate a row;
* an excluded path produces no row at all;
* a failed write logs and returns - a hook never breaks the turn.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from . import db, redact

logger = logging.getLogger(__name__)

PENDING_LIMIT = 512

_local = threading.local()
_pending: "OrderedDict[str, dict]" = OrderedDict()
_pending_lock = threading.Lock()


def _conn():
    """One connection per thread, opened lazily against the plugin database."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = db.connect()
        _local.conn = conn
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash_args(args: Any) -> str:
    try:
        encoded = json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        encoded = repr(args)
    return hashlib.sha1(encoded.encode("utf-8", "replace")).hexdigest()[:12]


def _event_id(
    session_id: str, turn_id: str, tool: str, args_hash: str, when: str
) -> str:
    """sha1(session|turn|tool|args_hash|minute).

    The minute is the coarse part of the key: two identical calls in the same
    minute are one event, which is what folds a retry storm into a single
    ledger line.
    """
    minute = (when or _now())[:16]
    material = "|".join((session_id or "", turn_id or "", tool or "", args_hash, minute))
    return hashlib.sha1(material.encode("utf-8", "replace")).hexdigest()


_READ_TOOLS = {
    "read_file",
    "list_directory",
    "grep",
    "glob",
    "search",
    "web_search",
    "web_fetch",
    "fetch",
    "skill_view",
    "session_search",
    "memory_search",
    "window_screenshot",
    "get_screenshot_of_window_as_json",
}
_WRITE_TOOLS = {
    "write_file",
    "edit_file",
    "apply_patch",
    "str_replace_editor",
    "create_file",
    "delete_file",
}
_SEND_TOOLS = {
    "send_message",
    "send_email",
    "post_message",
    "telegram_send",
    "discord_send",
    "reply",
    "email_send",
}
_EXEC_HINTS = ("shell", "terminal", "exec", "run_command", "bash", "powershell", "cmd")

_TARGET_KEYS = (
    "path",
    "file_path",
    "filepath",
    "file",
    "filename",
    "directory",
    "repo",
    "repository",
    "url",
    "uri",
    "target",
    "cwd",
    "command",
    "query",
    "pattern",
    "name",
)


def action_of(tool: str, args: dict | None = None) -> str:
    """Classify a tool call into read | write | exec | send | approve."""
    name = (tool or "").lower()
    if name in _READ_TOOLS or name.startswith(("read_", "get_", "list_", "search_")):
        return "read"
    if name in _WRITE_TOOLS or name.startswith(("write_", "edit_", "create_")):
        return "write"
    if name in _SEND_TOOLS or name.startswith(("send_", "post_")):
        return "send"
    if any(hint in name for hint in _EXEC_HINTS):
        return "exec"
    return "exec" if isinstance((args or {}).get("command"), str) else "read"


def target_of(args: dict | None) -> str:
    """Pick the most useful single target out of a tool's arguments.

    Order matters: a path beats a url, a url beats a query. Only the value is
    normalised and stored - the rest of the arguments never leave this call.
    """
    if not isinstance(args, dict):
        return ""

    for key in _TARGET_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip()
            if key == "command":
                candidate = candidate.split()[0] if candidate.split() else candidate
            return redact.normalize_target(candidate)[:300]
    return ""


def _outcome_of_status(status: Any, exit_code: int | None = None) -> str:
    text = str(status or "").lower()
    if not text:
        # Some payload versions omit status; the exit code is the better signal
        # than assuming success.
        return "fail" if exit_code not in (None, 0) else "ok"
    if text in {"ok", "success", "completed"}:
        return "ok"
    if text in {"blocked", "denied"}:
        return "blocked"
    if text in {"cancelled", "canceled", "timeout", "pending"}:
        return "pending" if text == "pending" else "fail"
    if text in {"error", "failed", "fail"}:
        return "fail"
    return "ok" if not text else "fail"


def _remember(event_id: str, row: dict) -> None:
    with _pending_lock:
        _pending[event_id] = row
        _pending.move_to_end(event_id)
        while len(_pending) > PENDING_LIMIT:
            _pending.popitem(last=False)


def _forget(event_id: str) -> dict | None:
    with _pending_lock:
        return _pending.pop(event_id, None)


def _excluded(target: str, config: dict) -> bool:
    patterns = config.get("excluded_paths") or []
    return redact.is_excluded(target, patterns)


def record_tool_start(config: dict, **payload) -> None:
    """pre_tool_call - a pending row, so a crash still leaves a trace."""
    try:
        tool = payload.get("tool_name") or ""
        args = payload.get("args") or {}
        target = target_of(args)
        if _excluded(target, config):
            return

        when = _now()
        session_id = payload.get("session_id") or ""
        turn_id = payload.get("turn_id") or ""
        args_hash = _hash_args(args)
        event_id = _event_id(session_id, turn_id, tool, args_hash, when)
        call_id = payload.get("tool_call_id") or event_id

        row = {
            "event_id": event_id,
            "ts_utc": when,
            "session_id": session_id or None,
            "turn_id": turn_id or None,
            "subagent_id": payload.get("task_id") if payload.get("task_id") != session_id else None,
            "kind": "tool",
            "actor": "subagent" if payload.get("subagent_id") else "agent",
            "tool": tool or None,
            "target": target or None,
            "action": action_of(tool, args),
            "outcome": "pending",
            "exit_code": None,
            "duration_ms": None,
            "cost_usd": None,
            "tokens_in": None,
            "tokens_out": None,
            "summary": None,
            "error_sig": None,
            "redacted": 0,
            "raw_ref": call_id,
        }
        _remember(call_id, row)
        db.insert_event(_conn(), row)
    except Exception:  # a broken hook must never break the turn
        logger.warning("imprint: pre_tool_call capture failed", exc_info=True)


def record_tool_end(config: dict, **payload) -> None:
    """post_tool_call - close the pending row with outcome, timing and error."""
    try:
        tool = payload.get("tool_name") or ""
        args = payload.get("args") or {}
        target = target_of(args)
        if _excluded(target, config):
            return

        when = _now()
        session_id = payload.get("session_id") or ""
        turn_id = payload.get("turn_id") or ""
        call_id = payload.get("tool_call_id") or ""

        # Correlate on the call's own id, never on a recomputed timestamp key:
        # a slow call that crosses a minute boundary is still one call.
        pending = (_forget(call_id) if call_id else None) or {}
        if not pending:
            fallback_id = _event_id(session_id, turn_id, tool, _hash_args(args), when)
            pending = _forget(fallback_id) or {}

        event_id = pending.get("event_id") or _event_id(
            session_id, turn_id, tool, _hash_args(args), when
        )

        status = payload.get("status")
        exit_code = _exit_code_of(payload)
        outcome = _outcome_of_status(status, exit_code)
        summary, kinds = _summary_for(
            tool, target, outcome, payload.get("error_message"), exit_code
        )
        error_sig = redact.error_signature(str(payload.get("error_message") or "")) or None

        row = {
            "event_id": event_id,
            "ts_utc": pending.get("ts_utc") or when,
            "session_id": session_id or None,
            "turn_id": turn_id or None,
            "subagent_id": pending.get("subagent_id"),
            "kind": "tool",
            "actor": pending.get("actor") or "agent",
            "tool": tool or None,
            "target": target or pending.get("target"),
            "action": pending.get("action") or action_of(tool, args),
            "outcome": outcome,
            "exit_code": exit_code,
            "duration_ms": payload.get("duration_ms"),
            "cost_usd": None,
            "tokens_in": None,
            "tokens_out": None,
            "summary": summary or None,
            "error_sig": error_sig,
            "redacted": 1 if kinds else 0,
            "raw_ref": call_id or pending.get("raw_ref"),
        }

        conn = _conn()
        if pending:
            conn.execute(
                "UPDATE events SET outcome=?, exit_code=?, duration_ms=?, summary=?, "
                "error_sig=?, redacted=?, target=COALESCE(target, ?), raw_ref=COALESCE(?, raw_ref) "
                "WHERE event_id=?",
                (
                    row["outcome"],
                    row["exit_code"],
                    row["duration_ms"],
                    row["summary"],
                    row["error_sig"],
                    row["redacted"],
                    row["target"],
                    row["raw_ref"],
                    event_id,
                ),
            )
            conn.commit()
        else:
            db.insert_event(conn, row)
    except Exception:
        logger.warning("imprint: post_tool_call capture failed", exc_info=True)


def _summary_for(
    tool: str, target: str, outcome: str, error_message: Any, exit_code: int | None
) -> tuple[str, tuple[str, ...]]:
    """Describe the call; never copy the tool's output into the ledger.

    The summary is built from the call's own metadata and, on failure, the
    first line of the error. Results, file contents and arguments never reach
    this function.
    """
    subject = f"{tool or 'tool'}"
    if target:
        subject = f"{subject} on {target}"

    if outcome == "fail":
        detail, kinds = redact.summarize(str(error_message or ""), limit=160)
        suffix = f" (exit {exit_code})" if exit_code is not None else ""
        if detail:
            return f"{subject} failed: {detail}{suffix}", kinds
        return f"{subject} failed{suffix}", ()

    if outcome == "blocked":
        return f"{subject} was blocked before it ran", ()
    if outcome == "pending":
        return f"{subject} did not finish", ()
    return f"{subject} completed", ()


def _exit_code_of(payload: dict) -> int | None:
    for key in ("exit_code", "returncode", "return_code"):
        value = payload.get(key)
        if isinstance(value, int):
            return value

    result = payload.get("result")
    if isinstance(result, dict):
        for key in ("exit_code", "returncode", "return_code"):
            value = result.get(key)
            if isinstance(value, int):
                return value
    return None


def record_api_call(config: dict, **payload) -> None:
    """post_api_request - tokens and spend for one provider attempt."""
    try:
        usage = payload.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}

        tokens_in = _first_int(usage, "prompt_tokens", "input_tokens", "tokens_in")
        tokens_out = _first_int(usage, "completion_tokens", "output_tokens", "tokens_out")
        cost = _first_float(usage, "cost_usd", "cost", "total_cost")
        if cost is None:
            cost = _first_float(payload, "cost_usd", "cost")

        if tokens_in is None and tokens_out is None and cost is None:
            return

        when = payload.get("ended_at") or _now()
        session_id = payload.get("session_id") or ""
        turn_id = payload.get("turn_id") or ""
        model = payload.get("response_model") or payload.get("model") or ""

        row = {
            "event_id": _event_id(
                session_id,
                turn_id,
                f"llm:{model}",
                str(payload.get("api_request_id") or payload.get("api_call_count") or ""),
                when,
            ),
            "ts_utc": when,
            "session_id": session_id or None,
            "turn_id": turn_id or None,
            "subagent_id": None,
            "kind": "llm",
            "actor": "agent",
            "tool": model or None,
            "target": payload.get("provider") or None,
            "action": "call",
            "outcome": "ok",
            "exit_code": None,
            "duration_ms": _ms(payload.get("api_duration")),
            "cost_usd": cost,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "summary": None,
            "error_sig": None,
            "redacted": 0,
            "raw_ref": None,
        }
        db.insert_event(_conn(), row)
    except Exception:
        logger.warning("imprint: post_api_request capture failed", exc_info=True)


def record_approval_request(config: dict, **payload) -> None:
    """pre_approval_request - that a person was asked, and about what kind of thing."""
    try:
        surface = payload.get("surface") or "unknown"
        pattern_keys = payload.get("pattern_keys") or []
        if isinstance(pattern_keys, str):
            pattern_keys = [pattern_keys]
        category = str(payload.get("pattern_key") or (pattern_keys[0] if pattern_keys else "command"))
        summary, kinds = redact.summarize(f"approval requested: {category} ({surface})")

        when = _now()
        session_key = payload.get("session_key") or ""
        row = {
            "event_id": _event_id(session_key, "", "approval", category, when),
            "ts_utc": when,
            "session_id": session_key or None,
            "turn_id": None,
            "subagent_id": None,
            "kind": "approval",
            "actor": "human",
            "tool": None,
            "target": category[:300] if category else None,
            "action": "approve",
            "outcome": "pending",
            "exit_code": None,
            "duration_ms": None,
            "cost_usd": None,
            "tokens_in": None,
            "tokens_out": None,
            "summary": summary or None,
            "error_sig": None,
            "redacted": 1 if kinds else 0,
            "raw_ref": surface,
        }
        db.insert_event(_conn(), row)
    except Exception:
        logger.warning("imprint: pre_approval_request capture failed", exc_info=True)


def record_approval_response(config: dict, **payload) -> None:
    """post_approval_response - the decision, never the command it was about."""
    try:
        choice = str(payload.get("choice") or "unknown")
        surface = payload.get("surface") or "unknown"
        category = str(payload.get("pattern_key") or "command")
        outcome = (
            "ok"
            if choice in {"once", "session", "always", "allow", "approved"}
            else "blocked"
        )
        summary, kinds = redact.summarize(f"approval {choice} ({surface})")

        when = _now()
        session_key = payload.get("session_key") or ""
        row = {
            "event_id": _event_id(session_key, "", "decision", category, when),
            "ts_utc": when,
            "session_id": session_key or None,
            "turn_id": None,
            "subagent_id": None,
            "kind": "approval",
            "actor": "human",
            "tool": None,
            "target": category[:300] if category else None,
            "action": "approve",
            "outcome": outcome,
            "exit_code": None,
            "duration_ms": None,
            "cost_usd": None,
            "tokens_in": None,
            "tokens_out": None,
            "summary": summary or None,
            "error_sig": None,
            "redacted": 1 if kinds else 0,
            "raw_ref": surface,
        }
        db.insert_event(_conn(), row)
    except Exception:
        logger.warning("imprint: post_approval_response capture failed", exc_info=True)


def record_subagent_start(config: dict, **payload) -> None:
    """subagent_start - a delegated child exists, and who asked for it."""
    try:
        goal = payload.get("child_goal") or ""
        summary, kinds = redact.summarize(str(goal))
        when = _now()
        child = payload.get("child_session_id") or payload.get("child_subagent_id") or ""

        row = {
            "event_id": _event_id(
                payload.get("parent_session_id") or "",
                payload.get("parent_turn_id") or "",
                "subagent:start",
                child,
                when,
            ),
            "ts_utc": when,
            "session_id": payload.get("parent_session_id") or None,
            "turn_id": payload.get("parent_turn_id") or None,
            "subagent_id": child or None,
            "kind": "message",
            "actor": "subagent",
            "tool": payload.get("child_role") or None,
            "target": child or None,
            "action": "delegate",
            "outcome": "pending",
            "exit_code": None,
            "duration_ms": None,
            "cost_usd": None,
            "tokens_in": None,
            "tokens_out": None,
            "summary": summary or None,
            "error_sig": None,
            "redacted": 1 if kinds else 0,
            "raw_ref": None,
        }
        db.insert_event(_conn(), row)
    except Exception:
        logger.warning("imprint: subagent_start capture failed", exc_info=True)


def record_subagent_stop(config: dict, **payload) -> None:
    """subagent_stop - close the child's row with its outcome and duration."""
    try:
        when = _now()
        child = payload.get("child_session_id") or payload.get("child_subagent_id") or ""
        summary, kinds = redact.summarize(str(payload.get("child_summary") or ""))
        status = _outcome_of_status(payload.get("status") or payload.get("child_status"))

        row = {
            "event_id": _event_id(
                payload.get("parent_session_id") or "",
                payload.get("parent_turn_id") or "",
                "subagent:stop",
                child,
                when,
            ),
            "ts_utc": when,
            "session_id": payload.get("parent_session_id") or None,
            "turn_id": payload.get("parent_turn_id") or None,
            "subagent_id": child or None,
            "kind": "message",
            "actor": "subagent",
            "tool": payload.get("child_role") or None,
            "target": child or None,
            "action": "delegate",
            "outcome": status,
            "exit_code": None,
            "duration_ms": payload.get("duration_ms"),
            "cost_usd": None,
            "tokens_in": None,
            "tokens_out": None,
            "summary": summary or None,
            "error_sig": None,
            "redacted": 1 if kinds else 0,
            "raw_ref": None,
        }
        db.insert_event(_conn(), row)
    except Exception:
        logger.warning("imprint: subagent_stop capture failed", exc_info=True)


def record_session_reset(config: dict, **payload) -> None:
    """on_session_reset - a boundary marker, so a week has seams to split on."""
    try:
        when = _now()
        old = payload.get("old_session_id") or payload.get("session_id") or ""
        new = payload.get("new_session_id") or ""
        summary, kinds = redact.summarize(
            f"session reset on {payload.get('platform') or 'unknown'}"
        )

        row = {
            "event_id": _event_id(old, "", "session:reset", new, when),
            "ts_utc": when,
            "session_id": old or None,
            "turn_id": None,
            "subagent_id": None,
            "kind": "message",
            "actor": "system",
            "tool": None,
            "target": payload.get("platform") or None,
            "action": "reset",
            "outcome": "ok",
            "exit_code": None,
            "duration_ms": None,
            "cost_usd": None,
            "tokens_in": None,
            "tokens_out": None,
            "summary": summary or None,
            "error_sig": None,
            "redacted": 1 if kinds else 0,
            "raw_ref": None,
        }
        db.insert_event(_conn(), row)
    except Exception:
        logger.warning("imprint: on_session_reset capture failed", exc_info=True)


def _first_int(source: dict, *keys: str) -> int | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _first_float(source: dict, *keys: str) -> float | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _ms(seconds: Any) -> int | None:
    if isinstance(seconds, (int, float)):
        return int(round(float(seconds) * 1000))
    return None
