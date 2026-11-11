"""Golden test: the fixture week compiles to a book with a printed ratio.

No model is called. The stub returns prose that cites real event ids, so the
test is about the machinery - ledger in, chapters out, citations checked,
artefacts written - and never about a model's mood.
"""

import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from imprint_plugin import db, pipeline

WEEK = "2026-W45"
FIXTURE = Path(__file__).parent / "fixtures" / "week.json"


class StubLlm:
    """A stand-in for ctx.llm that cites the events it was given."""

    def __init__(self):
        self.calls = 0

    def complete(self, messages, **kwargs):
        self.calls += 1
        prompt = messages[-1]["content"]
        ids = re.findall(r'"id": "(e\d+)"', prompt) or ["e1"]

        sentences = [
            f"Work continued on the project [{ids[0]}].",
            f"The next step followed the same thread [{ids[min(1, len(ids) - 1)]}].",
            f"It closed out where it started [{ids[-1]}].",
        ]
        return type("Result", (), {"text": " ".join(sentences)})()


class CompileGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls._saved = {
            key: os.environ.get(key) for key in ("IMPRINT_DATA_DIR", "IMPRINT_DB_PATH")
        }
        os.environ["IMPRINT_DATA_DIR"] = str(cls.tmp / "data")
        os.environ["IMPRINT_DB_PATH"] = str(cls.tmp / "ledger.db")

        conn = db.connect(cls.tmp / "ledger.db")
        for index, row in enumerate(json.loads(FIXTURE.read_text(encoding="utf-8")), start=1):
            row = dict(row)
            row["event_id"] = f"golden-{index}"
            db.insert_event(conn, row)
        conn.close()

        cls.llm = StubLlm()
        cls.result = pipeline.compile_week(WEEK, "epic", llm=cls.llm)
        cls.book_dir = cls.tmp / "data" / "books" / WEEK

    @classmethod
    def tearDownClass(cls):
        for key, value in cls._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_book_is_written(self):
        self.assertTrue(self.result["book_id"] > 0)
        self.assertGreaterEqual(self.result["chapters"], 1)

    def test_every_chapter_has_citations(self):
        self.assertTrue(self.result["verified"] > 0)
        self.assertLessEqual(self.result["verified"], self.result["sentences"])

    def test_the_stub_was_asked_for_prose(self):
        self.assertGreater(self.llm.calls, 0)

    def test_html_carries_superscript_citations(self):
        html = (self.book_dir / "book.html").read_text(encoding="utf-8")
        self.assertIn('class="cite"', html)
        self.assertIn("carry a verified", html)

    def test_epub_has_the_mimetype_first(self):
        with zipfile.ZipFile(self.book_dir / "book.epub") as archive:
            names = archive.namelist()
            self.assertEqual("mimetype", names[0])
            self.assertEqual("application/epub+zip", archive.read("mimetype").decode())
            self.assertIn("OEBPS/content.opf", names)

    def test_the_ledger_is_queryable_afterward(self):
        conn = db.connect(self.tmp / "ledger.db")
        row = conn.execute("SELECT sentences_total, sentences_verified FROM books").fetchone()
        conn.close()
        self.assertGreater(row["sentences_total"], 0)
        self.assertGreater(row["sentences_verified"], 0)

    def test_the_executive_page_reads_as_a_report(self):
        conn = db.connect(self.tmp / "ledger.db")
        book_id = conn.execute("SELECT id FROM books").fetchone()[0]
        conn.close()
        text = pipeline.executive_text(book_id)
        self.assertIn("IMPRINT", text)
        self.assertIn("Shipped", text)
        self.assertIn("Spend", text)

    def test_burn_removes_the_week(self):
        tmp = Path(tempfile.mkdtemp())
        saved = {key: os.environ.get(key) for key in ("IMPRINT_DATA_DIR", "IMPRINT_DB_PATH")}
        try:
            os.environ["IMPRINT_DATA_DIR"] = str(tmp / "data")
            os.environ["IMPRINT_DB_PATH"] = str(tmp / "ledger.db")
            conn = db.connect(tmp / "ledger.db")
            for index, row in enumerate(
                json.loads(FIXTURE.read_text(encoding="utf-8"))[:6], start=1
            ):
                row = dict(row)
                row["event_id"] = f"burn-{index}"
                db.insert_event(conn, row)
            conn.close()

            pipeline.compile_week(WEEK, "noir", llm=StubLlm())
            removed = pipeline.burn_week(WEEK)
            self.assertGreater(removed["events"], 0)

            conn = db.connect(tmp / "ledger.db")
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM books").fetchone()[0])
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            conn.close()
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
