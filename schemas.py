"""Tool schemas - the only thing the model reads to decide when to call us.

Every description states the contract plainly, because a tool the model
misreads is a tool that never fires at the right moment.
"""

COMPILE = {
    "name": "imprint_compile",
    "description": (
        "Compile a week of Hermes activity into a cited, typeset book. "
        "Builds or rebuilds the chapter set from the event ledger, runs prose "
        "generation and the citation checker, and writes PDF, EPUB and HTML. "
        "Every sentence in the finished chapter cites the ledger event it came from. "
        "Use this when the user asks for their week as a book, report, or retrospective."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "week": {
                "type": "string",
                "description": "ISO week label such as '2026-W45'. Omit for the current week.",
            },
            "genre": {
                "type": "string",
                "enum": ["epic", "noir", "ships-log"],
                "description": (
                    "Voice for the prose. Facts are identical in every genre; "
                    "only tone and chapter-title style change."
                ),
            },
        },
        "required": [],
    },
}

PREVIEW = {
    "name": "imprint_preview",
    "description": (
        "Return the executive edition of a compiled book as plain text: what "
        "shipped, what is blocked, what is owed, and what it cost. One page, "
        "no prose. Use this for a status report without opening the book."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "book_id": {
                "type": "integer",
                "description": "Book id from a previous compile. Omit for the most recent book.",
            },
        },
        "required": [],
    },
}

STATUS = {
    "name": "imprint_status",
    "description": (
        "Report the ledger's health: events recorded, date range, last compile, "
        "open threads and how many weeks are available to compile. Use this "
        "before compiling to check there is a week to write about."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

IMPORT = {
    "name": "imprint_import",
    "description": (
        "Backfill the ledger from the active Hermes profile's persisted session "
        "store, read-only and bounded to a window of days. Disclosed, one-time, "
        "and refuses rather than guessing when the store's shape is unexpected."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "How many days back to read. Default 7.",
            },
        },
        "required": [],
    },
}

ALL = (COMPILE, PREVIEW, STATUS, IMPORT)
