"""The importer against a store shaped like the real one."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from imprint_plugin import db, importer


def make_store(directory: Path) -> Path:
    """A miniature state.db: float epochs, mixed roles, one stale row."""
    path = directory / "state.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, "
        "content TEXT, timestamp REAL)"
    )
    now = datetime.now(timezone.utc)
    rows = [
        ("s1", "user", "tighten the queue lock", now - timedelta(hours=3)),
        ("s1", "assistant", "the lock is renewed now", now - timedelta(hours=2)),
        ("s1", "system", "you are a helpful onboarding assistant", now - timedelta(hours=2)),
        ("s1", "tool", '{"output": "ok"}', now - timedelta(hours=2)),
        ("s1", "user", "this is older than the window", now - timedelta(days=30)),
    ]
    for session, role, content, when in rows:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session, role, content, when.timestamp()),
        )
    conn.commit()
    conn.close()
    return path


class Import(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        make_store(self.tmp)
        self._saved = {
            key: os.environ.get(key)
            for key in ("HERMES_HOME", "IMPRINT_DB_PATH", "IMPRINT_DATA_DIR")
        }
        os.environ["HERMES_HOME"] = str(self.tmp)
        os.environ["IMPRINT_DB_PATH"] = str(self.tmp / "ledger.db")
        os.environ["IMPRINT_DATA_DIR"] = str(self.tmp / "data")
        # The store is resolved through the harness now, not through os.environ.
        # Patching the seam is what a unit test should do: this asserts we ask
        # the resolver, not that we reimplement it.
        self._home = mock.patch.object(db, "active_home", return_value=str(self.tmp))
        self._home.start()

    def tearDown(self):
        self._home.stop()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_the_window_and_only_people(self):
        result = importer.import_window(days=7)
        self.assertEqual(2, result["written"])
        self.assertEqual(2, result["skipped"])  # the system row and the tool row

        conn = db.connect(self.tmp / "ledger.db")
        actors = {row["actor"] for row in conn.execute("SELECT actor FROM events")}
        conn.close()
        self.assertEqual({"human", "agent"}, actors)

    def test_second_pass_is_idempotent(self):
        importer.import_window(days=7)
        result = importer.import_window(days=7)
        self.assertEqual(0, result["written"])
        self.assertEqual(2, result["already_present"])

    def test_numeric_epochs_are_understood(self):
        """A float timestamp must not be compared against an ISO string."""
        conn = sqlite3.connect(str(self.tmp / "state.db"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        bound = importer._cutoff_for(conn, "timestamp", cutoff)
        conn.close()
        self.assertIsInstance(bound, float)
        self.assertGreater(bound, 1_700_000_000)

    def test_missing_store_refuses(self):
        with mock.patch.object(db, "active_home", return_value=str(self.tmp / "nowhere")):
            with self.assertRaises(FileNotFoundError):
                importer.import_window(days=7)

    def test_does_not_fall_back_to_the_launch_profile(self):
        """HERMES_HOME points at a good store; the active profile has none.

        The importer must refuse rather than import the launch profile's
        transcripts into this profile's ledger. That fallback was the bug in a
        gateway serving several profiles.
        """
        self.assertTrue((self.tmp / "state.db").is_file())
        with mock.patch.object(db, "active_home", return_value=str(self.tmp / "other")):
            with self.assertRaises(FileNotFoundError):
                importer.import_window(days=7)


if __name__ == "__main__":
    unittest.main()
