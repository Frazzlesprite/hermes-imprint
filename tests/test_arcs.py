"""Arc extraction against the fixture week.

The fixture is built with one of each act break, so these assertions are about
behaviour, not about a snapshot of the implementation.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from imprint_plugin import arcs, cast, db

WEEK = "2026-W45"
FIXTURE = Path(__file__).parent / "fixtures" / "week.json"


def ledger(path: Path):
    """A ledger at ``path`` loaded with the fixture week."""
    conn = db.connect(path)

    for index, row in enumerate(json.loads(FIXTURE.read_text(encoding="utf-8")), start=1):
        row = dict(row)
        row["event_id"] = f"fixture-{index}"
        db.insert_event(conn, row)
    return conn


class FixtureWeek(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls.conn = ledger(Path(cls._tmp) / "fixture.db")
        cls.events = arcs.load_events(cls.conn, WEEK)
        cls.quests = arcs.split_quests(cls.events)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_the_week_loads(self):
        self.assertEqual(18, len(self.events))

    def test_quests_split_on_project_and_gap(self):
        self.assertEqual(5, len(self.quests))

    def test_a_failure_streak_merges_into_one_chapter(self):
        chapters = arcs.build_chapters(self.quests[0])
        self.assertEqual(1, len(chapters))
        self.assertEqual("the breakthrough", chapters[0]["label"])

    def test_an_approval_is_the_rescue(self):
        self.assertEqual("the rescue", arcs.build_chapters(self.quests[1])[0]["label"])

    def test_a_delegation_is_the_hand_off(self):
        self.assertEqual("the hand-off", arcs.build_chapters(self.quests[3])[0]["label"])

    def test_a_quest_that_ends_failing_is_the_dead_end(self):
        self.assertEqual("the dead end", arcs.build_chapters(self.quests[4])[0]["label"])

    def test_an_unclosed_todo_is_an_open_thread(self):
        self.assertTrue(arcs.unresolved(self.quests[2]))
        self.assertEqual("stalled", arcs.quest_status(self.quests[2]))

    def test_a_closed_quest_is_done(self):
        self.assertEqual("done", arcs.quest_status(self.quests[1]))

    def test_motif_needs_three_occurrences(self):
        motifs = arcs.motifs(self.events)
        self.assertEqual(1, len(motifs))
        self.assertGreaterEqual(motifs[0]["count"], 3)
        self.assertIn("ModuleNotFoundError", motifs[0]["signature"])

    def test_stakes_reward_files_and_retries(self):
        self.assertGreater(arcs.stakes(self.quests[0]), arcs.stakes(self.quests[3]))

    def test_chapters_are_ordered_by_stakes(self):
        ordered = sorted(self.quests, key=arcs.stakes, reverse=True)
        self.assertNotEqual(
            [id(q) for q in ordered], [id(q) for q in self.quests],
            "fixture should not already be in stakes order",
        )


class Cast(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls.conn = ledger(Path(cls._tmp) / "cast.db")
        cls.cast = cast.build(arcs.load_events(cls.conn, WEEK))

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_tool_counts_and_failure_rate(self):
        tools = {item["name"]: item for item in self.cast["tools"]}
        self.assertIn("shell", tools)
        self.assertEqual(7, tools["shell"]["count"])
        self.assertEqual(6, tools["shell"]["failures"])
        self.assertAlmostEqual(6 / 7, tools["shell"]["failure_rate"], places=3)

    def test_paths_are_grouped_by_project(self):
        names = [item["name"] for item in self.cast["paths"]]
        self.assertIn("C:/work/imprint-plugin", names)

    def test_people_come_from_mentions_only(self):
        self.assertEqual(["hermes-docs"], [item["name"] for item in self.cast["people"]])


class EdgeCases(unittest.TestCase):
    def test_empty_quest_has_no_chapters(self):
        self.assertEqual([], arcs.build_chapters([]))

    def test_single_event_is_one_chapter(self):
        chapter = arcs.build_chapters([{"ts_utc": "2026-11-02T09:00:00+00:00", "outcome": "ok"}])
        self.assertEqual(1, len(chapter))

    def test_no_events_no_quests(self):
        self.assertEqual([], arcs.split_quests([]))


if __name__ == "__main__":
    unittest.main()
