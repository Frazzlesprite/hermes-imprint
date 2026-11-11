"""Compile the fixture week into a real book, for the demo and for reviews.

This is a development tool, not part of the plugin. It seeds a throwaway ledger
from ``tests/fixtures/week.json`` and runs the same pipeline the agent tool
runs, with a stub model that cites real events.

    python tools/seed_demo.py            # writes .demo/
    python tools/seed_demo.py --genre noir
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

_PACKAGE = "imprint_plugin"
if _PACKAGE not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        _PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_PACKAGE] = _module
    _spec.loader.exec_module(_module)

from imprint_plugin import db, pipeline  # noqa: E402

WEEK = "2026-W45"
FIXTURE = ROOT / "tests" / "fixtures" / "week.json"


class StubLlm:
    """Cites the events it is handed, so the checker has something real to check."""

    def complete(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        ids = re.findall(r'"id": "(e\d+)"', prompt) or ["e1"]
        sentences = [
            f"Work continued on the project [{ids[0]}].",
            f"The next step followed the same thread [{ids[min(1, len(ids) - 1)]}].",
            f"It closed out where it started [{ids[-1]}].",
        ]
        print("      (stub prose: {n} events in prompt)".format(n=len(ids)))
        return type("Result", (), {"text": " ".join(sentences)})()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--genre", default="epic", choices=("epic", "noir", "ships-log"))
    parser.add_argument("--out", default=str(ROOT / ".demo"))
    args = parser.parse_args()

    out = Path(args.out)
    os.environ["IMPRINT_DATA_DIR"] = str(out / "data")
    os.environ["IMPRINT_DB_PATH"] = str(out / "ledger.db")

    conn = db.connect(out / "ledger.db")
    for index, row in enumerate(json.loads(FIXTURE.read_text(encoding="utf-8")), start=1):
        row = dict(row)
        row["event_id"] = f"demo-{index}"
        db.insert_event(conn, row)
    conn.close()

    result = pipeline.compile_week(WEEK, args.genre, llm=StubLlm())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
