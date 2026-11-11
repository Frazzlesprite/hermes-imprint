"""Imprint - your week, in print.

Compiles a week of Hermes activity into a typeset book whose every sentence
carries a citation to the ledger event it came from.

Registration only. The work lives in the modules beside this file.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import capture, schemas, tools

logger = logging.getLogger(__name__)

_TOOLSET = "imprint"

_TOOLS = (
    (schemas.COMPILE, tools.compile_week, "Compile a week into a cited book"),
    (schemas.PREVIEW, tools.preview_book, "Read a book's executive edition"),
    (schemas.STATUS, tools.ledger_status, "Report ledger health"),
    (schemas.IMPORT, tools.import_history, "Backfill from the session store"),
)

_HOOKS = (
    ("pre_tool_call", capture.record_tool_start),
    ("post_tool_call", capture.record_tool_end),
    ("post_api_request", capture.record_api_call),
    ("pre_approval_request", capture.record_approval_request),
    ("post_approval_response", capture.record_approval_response),
    ("subagent_start", capture.record_subagent_start),
    ("subagent_stop", capture.record_subagent_stop),
    ("on_session_reset", capture.record_session_reset),
)


def _settings(ctx) -> dict:
    """Read the plugin's own settings, with the manifest defaults intact."""
    return {
        "book_title": ctx.get_config("book_title", "The Week"),
        "genre": ctx.get_config("genre", "epic"),
        "week_start_day": ctx.get_config("week_start_day", "monday"),
        "excluded_paths": ctx.get_config("excluded_paths", []) or [],
        "retain_weeks": ctx.get_config("retain_weeks", 52),
    }


def _hook(ctx, recorder):
    """Bind one recorder to this plugin's settings.

    The callback accepts ``**kwargs`` on purpose: Hermes adds payload fields
    additively, and a fixed signature would drop them on the next upgrade.
    """

    def callback(**kwargs):
        recorder(_settings(ctx), **kwargs)

    callback.__name__ = f"imprint_{recorder.__name__}"
    callback.__doc__ = f"Imprint: {recorder.__doc__ or ''}".strip()
    return callback


def _tool_handler(ctx, handler):
    """Give a tool handler the plugin's model and settings without module globals."""

    def wrapped(args, **kwargs):
        return handler(args, llm=ctx.llm, settings=_settings(ctx), **kwargs)

    wrapped.__name__ = getattr(handler, "__name__", "handler")
    return wrapped


def register(ctx) -> None:
    """Wire hooks, tools, the slash command and the bundled skill."""
    for hook_name, recorder in _HOOKS:
        ctx.register_hook(hook_name, _hook(ctx, recorder))

    for schema, handler, description in _TOOLS:
        ctx.register_tool(
            name=schema["name"],
            toolset=_TOOLSET,
            schema=schema,
            handler=_tool_handler(ctx, handler),
            description=description,
            emoji="\U0001f4d6",
        )

    ctx.register_command(
        "imprint",
        _tool_handler(ctx, tools.slash_command),
        description="Compile the week into a book, or erase it",
        args_hint="[week] [burn|library|genre <name>]",
        argument_mode="text",
    )

    from . import cli

    ctx.register_cli_command(
        "imprint",
        "Compile a week of Hermes activity into a cited, typeset book",
        cli.setup,
        cli.handle,
    )

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                ctx.register_skill(child.name, skill_md)
