# Imprint

**Your week, in print.**

Imprint compiles a week of Hermes activity into a typeset book. Chapters come
from a verified event ledger, every sentence carries a citation to the event it
came from, a one-page executive edition sits at the front, and the raw evidence
is printed at the back.

> **Every sentence cites the event it came from.**

---

## Disclosure - read this before installing

Imprint observes and records. What that means in practice:

| What | Detail |
|---|---|
| **Network** | None of its own. The only outbound calls are the model calls you already configured, made through `ctx.llm` during prose generation and fact-checking. No telemetry, no analytics, no update check. |
| **Reads outside its own data** | Only `imprint_import`, which opens the active profile's `state.db` **read-only** and bounded to a requested window of days. Every other component reads only the plugin's own database. |
| **Writes** | Only the plugin data directory (`plugin_data_dir("imprint")`). Never the install tree, never a config file, never another plugin's data. |
| **Shell** | Runs `typst compile` when Typst is on `PATH`, and `typst --version` to check it. Nothing else. |
| **Stored content** | Summaries of 280 characters or fewer, redacted **at write time**. Tool arguments are hashed, never stored. File contents, message bodies and command arguments never reach the ledger. |
| **Approvals** | Imprint observes approval prompts and records the decision. It never answers one, never auto-approves, and cannot veto a tool call. |
| **Erase** | `imprint_burn(week, confirm=true)` deletes that week's ledger rows, compiled artefacts and bible entries. There is no undo. |

PDF rendering uses [Typst](https://typst.app), which you install yourself. If
Typst is absent, Imprint still writes HTML and EPUB and says so in its result
rather than failing.

---

## What you get

- **A ledger**, written as Hermes runs: tool calls with outcome and duration,
  provider spend and tokens, approvals and their decisions, subagent lifetimes,
  session boundaries.
- **Quests and chapters**, extracted deterministically. A quest is a project and
  a stretch of work; a chapter begins at an act break - a failure streak that
  turned, a check that went from red to green, an approval that unblocked a
  stall, a change of approach.
- **Prose in one of three voices**: `epic`, `noir`, `ships-log`. The voice
  changes; the event set never does.
- **A canon checker** that runs before anything is printed. Deterministic rules
  first, a cheap semantic pass second, and a disposition: keep, rewrite once,
  or cut.
- **Artefacts**: A5 PDF via Typst, EPUB, and a self-contained HTML file.
- **An executive edition**: shipped, blocked, owed, spend, hours. The Friday
  status report that writes itself.
- **A Desktop library** with a shelf, page-turn preview, genre switch, and a
  status-bar chip. Plain ESM, SDK only.

The colophon prints the result honestly:

> *412 of 419 sentences carry a verified citation. 7 were cut.*

---

## Install

```bash
# from a checkout
hermes plugins install . --enable

# or from the catalog, once listed
hermes plugins install imprint
```

Then check it loaded:

```bash
hermes plugins doctor . --ci          # discovery, manifest, register(), registries
hermes plugins validate . --install-deps
```

Requires Hermes `>=0.23.0`. Python `>=3.11`.

For PDF output, install Typst and put it on `PATH`
(`winget install Typst.Typst`, `brew install typst`, or a pinned release from
the official GitHub releases page). Imprint does not download a binary.

---

## Use

| Surface | Call |
|---|---|
| Tool | `imprint_compile(week="2026-W45", genre="epic")` |
| Tool | `imprint_preview(book_id)` - the executive page as text |
| Tool | `imprint_status()` - ledger size, weeks available, open threads |
| Tool | `imprint_import(days=7)` - read-only backfill from the session store |
| Tool | `imprint_burn(week="2026-W45", confirm=true)` - erase |
| Slash | `/imprint`, `/imprint 2026-W45`, `/imprint status`, `/imprint library`, `/imprint burn` |
| Desktop | Sidebar -> **Imprint**; palette -> *Imprint: open the library* |

Settings live under `plugins.entries.imprint.settings`: `book_title`, `genre`,
`week_start_day`, `excluded_paths`, `retain_weeks`.

`excluded_paths` is the privacy switch you will actually use. A path under an
excluded prefix produces no row at all - it is dropped before insert, not
hidden afterward. Matching is case-insensitive on normalised separators.

---

## How the checking works

1. **Deterministic, always runs.** Every cited id exists and belongs to the
   chapter; every numeral in a sentence appears in a cited event; every
   specific entity (path, file, repo, identifier) appears in a cited event; no
   sentence without a citation.
2. **Semantic, optional.** A cheap model is asked, per sentence, whether its
   evidence supports it: `supports`, `partial`, `unrelated`.
3. **Disposition.** `supports` is kept. `partial` gets one rewrite attempt and
   is cut if that fails. `unrelated` is cut. No sentence is quietly kept.

If the semantic pass is unavailable, the deterministic stage still runs and the
ratio printed is the lower, honest one.

---

## Limitations

- **A week needs events.** A fresh install has an empty ledger. Come back after
  a week, or use `imprint_import` to backfill from the session store. If the
  store's shape is not recognised, Imprint refuses rather than guessing and the
  book begins at install.
- **Prose is the only stochastic stage.** It is gated, cached by event-set hash,
  and never runs during capture. **With no model configured, Imprint still
  prints**: the chapter is composed deterministically from the ledger, every
  sentence still cites its event, and the colophon says which path produced the
  book. It is plain on purpose; it is the honest floor, not the pitch.
- **The arc vocabulary is fixed**: *the breakthrough, the dead end, the rescue,
  the detour, the hand-off*. A chapter is never labelled with something invented
  for it.
- **The importer is deliberately narrow.** It reads a window, in read-only mode,
  and refuses on an unexpected schema.
- **Desktop and agent halves are separate processes.** The library page reads
  the plugin's own backend at `/api/plugins/imprint/`; the Python backend is
  mounted only when the plugin is in `plugins.enabled`.
- **v1 does not do** audio narration, illustration beyond one procedural cover,
  multi-user books, live streaming generation, or cloud sync.
- **Windows paths** are normalised to forward slashes and compared
  case-insensitively.

---

## Development

```bash
python -m unittest discover -s tests -t .        # 56 tests, no model calls
python tools/seed_demo.py --genre noir            # compile the fixture week
```

The fixture week (`tests/fixtures/week.json`, generated by `make_week.py`)
contains one of each act break, so the tests assert behaviour rather than a
snapshot.

Layout:

```
plugin.yaml  __init__.py  schemas.py  tools.py  pipeline.py
capture.py   importer.py  arcs.py     cast.py   prose.py   canon.py
redact.py    db.py
typeset/     book.typ, render.py       # PDF via Typst, EPUB + HTML always
desktop/     plugin.js                 # the library, plain ESM
dashboard/   plugin_api.py             # shelf + executive backend
skills/imprint/SKILL.md
tests/       fixtures/week.json, test_arcs.py, test_canon.py,
             test_redact.py, test_typeset.py
```

## Licence

MIT.
