---
name: imprint
description: Compile a week of Hermes activity into a cited, typeset book, or read the executive edition as a status report.
---

# Imprint

*Your week, in print.*

Imprint turns the ledger of what actually happened - tool calls, approvals,
errors, subagents, spend - into a book where every sentence carries a citation
to the event it came from. The raw evidence is printed at the back.

## When to use this skill

Use it when the user asks for any of:

- their week as a book, a report, or a retrospective
- a Friday status report: what shipped, what is blocked, what is owed, what it cost
- a record of what an agent actually did, with evidence
- the same week in a different voice (epic, noir, ships-log)

## Reading the result honestly

The colophon prints a verification ratio. Read it out rather than around it:

- *412 of 419 sentences carry a verified citation. 7 were cut.*

Those seven were removed because a deterministic check or the semantic pass
could not support them. Do not describe a cut sentence as a minor issue; it is
the checker working.

## Commands

| Call | What it does |
|---|---|
| `imprint_status()` | ledger size, weeks available, open threads |
| `imprint_compile(week, genre)` | build or rebuild a book |
| `imprint_preview(book_id)` | the executive page as text |
| `imprint_import(days)` | read-only backfill from the session store |
| `imprint_burn(week, confirm)` | erase a week permanently |

Slash command: `/imprint [week]`, `/imprint burn [week]`, `/imprint library`,
`/imprint status`.

## What Imprint does not do

- It never stores raw tool payloads. Summaries are 280 characters or fewer and
  are redacted at write time.
- It never records a path matching `excluded_paths`.
- It never auto-approves anything. It watches approvals; it does not answer them.
- It does not send your data anywhere. The only network calls are the model
  calls you already configured.

## If there is nothing to print

A fresh install has an empty ledger. Either come back after a week of work, or
run `imprint_import(days=7)` to backfill from the profile's session store. If
the store's shape is not recognised, Imprint refuses rather than guessing, and
the book begins at install.
