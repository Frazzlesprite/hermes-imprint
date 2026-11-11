"""The offline composer: same facts, three registers, every sentence cited."""

import re
import unittest

from imprint_plugin import canon, prose

EVENTS = [
    {
        "id": 1,
        "ts_utc": "2026-11-02T09:00:00+00:00",
        "kind": "tool",
        "tool": "terminal",
        "target": "C:/work/atlas-api",
        "action": "exec",
        "outcome": "fail",
        "summary": "pytest stopped on the queue lock",
        "error_sig": None,
    },
    {
        "id": 2,
        "ts_utc": "2026-11-02T09:12:00+00:00",
        "kind": "tool",
        "tool": "terminal",
        "target": "C:/work/atlas-api",
        "action": "exec",
        "outcome": "fail",
        "summary": "pytest stopped again",
        "error_sig": None,
    },
    {
        "id": 3,
        "ts_utc": "2026-11-02T09:20:00+00:00",
        "kind": "tool",
        "tool": "edit_file",
        "target": "C:/work/atlas-api/src/locks.py",
        "action": "write",
        "outcome": "ok",
        "summary": "edited locks.py",
        "error_sig": None,
    },
    {
        "id": 4,
        "ts_utc": "2026-11-02T09:31:00+00:00",
        "kind": "tool",
        "tool": "terminal",
        "target": "C:/work/atlas-api",
        "action": "exec",
        "outcome": "ok",
        "summary": "pytest passed",
        "error_sig": None,
    },
]

WEEK = [
    {"id": 1, "ts_utc": "2026-11-02T09:00:00+00:00", "kind": "tool", "tool": "read_file",
     "target": "C:/work/atlas-api/README.md", "action": "read", "outcome": "ok",
     "summary": "read the README", "error_sig": None},
    {"id": 2, "ts_utc": "2026-11-02T09:06:00+00:00", "kind": "tool", "tool": "read_file",
     "target": "C:/work/atlas-api/docs/ARCH.md", "action": "read", "outcome": "ok",
     "summary": "read the architecture notes", "error_sig": None},
    {"id": 3, "ts_utc": "2026-11-02T09:12:00+00:00", "kind": "tool", "tool": "edit_file",
     "target": "C:/work/atlas-api/src/queue.py", "action": "write", "outcome": "ok",
     "summary": "edited queue.py", "error_sig": None},
    {"id": 4, "ts_utc": "2026-11-02T09:20:00+00:00", "kind": "tool", "tool": "terminal",
     "target": "C:/work/atlas-api", "action": "exec", "outcome": "fail",
     "summary": "pytest failed on the lock", "error_sig": "LOCK"},
    {"id": 5, "ts_utc": "2026-11-02T09:24:00+00:00", "kind": "tool", "tool": "terminal",
     "target": "C:/work/atlas-api", "action": "exec", "outcome": "fail",
     "summary": "pytest failed again", "error_sig": "LOCK"},
    {"id": 6, "ts_utc": "2026-11-02T09:28:00+00:00", "kind": "tool", "tool": "terminal",
     "target": "C:/work/atlas-api", "action": "exec", "outcome": "fail",
     "summary": "pytest failed a third time", "error_sig": "LOCK"},
    {"id": 7, "ts_utc": "2026-11-02T09:36:00+00:00", "kind": "tool", "tool": "edit_file",
     "target": "C:/work/atlas-api/src/queue.py", "action": "write", "outcome": "ok",
     "summary": "guarded the retry", "error_sig": None},
    {"id": 8, "ts_utc": "2026-11-02T09:44:00+00:00", "kind": "tool", "tool": "terminal",
     "target": "C:/work/atlas-api", "action": "exec", "outcome": "ok",
     "summary": "pytest passed", "error_sig": None},
    {"id": 9, "ts_utc": "2026-11-02T09:52:00+00:00", "kind": "approval", "tool": None,
     "target": "database_migration", "action": "approve", "outcome": "pending",
     "summary": "approval requested", "error_sig": None},
    {"id": 10, "ts_utc": "2026-11-02T09:53:00+00:00", "kind": "approval", "tool": None,
     "target": "database_migration", "action": "approve", "outcome": "ok",
     "summary": "approval once", "error_sig": None},
    {"id": 11, "ts_utc": "2026-11-02T10:00:00+00:00", "kind": "tool", "tool": "terminal",
     "target": "C:/work/atlas-api", "action": "exec", "outcome": "ok",
     "summary": "the migration ran", "error_sig": None},
    {"id": 12, "ts_utc": "2026-11-02T10:10:00+00:00", "kind": "tool", "tool": "write_file",
     "target": "C:/work/atlas-api/docs/locks.md", "action": "write", "outcome": "ok",
     "summary": "wrote the lock notes", "error_sig": None},
]

WEEK_BY_ID = {f"e{row['id']}": row for row in WEEK}
WEEK_IDS = set(WEEK_BY_ID)

BY_ID = {f"e{row['id']}": row for row in EVENTS}
ALLOWED = set(BY_ID)



class Composer(unittest.TestCase):
    def test_every_sentence_is_cited(self):
        for genre in prose.GENRES:
            body = prose.offline_chapter(genre, EVENTS)
            result = canon.verify(body, ALLOWED, BY_ID)
            self.assertGreater(result["sentences_total"], 0, genre)
            self.assertEqual(
                result["sentences_verified"],
                result["sentences_total"],
                f"{genre} lost a sentence: {result['cut']}",
            )

    def test_genres_differ_in_voice_not_facts(self):
        epic = prose.offline_chapter("epic", EVENTS)
        noir = prose.offline_chapter("noir", EVENTS)
        self.assertNotEqual(epic, noir)
        self.assertEqual(set(canon.cited_ids(epic)), set(canon.cited_ids(noir)))

    def test_composition_is_deterministic(self):
        self.assertEqual(
            prose.offline_chapter("epic", EVENTS), prose.offline_chapter("epic", EVENTS)
        )

    def test_a_chapter_does_not_repeat_a_frame(self):
        body = prose.offline_chapter("epic", EVENTS)
        sentences = canon.sentences(body)
        tails = [sentence.split(",")[-1] for sentence in sentences]
        self.assertEqual(len(tails), len(set(tails)))

    def test_empty_input_is_empty_output(self):
        self.assertEqual("", prose.offline_chapter("epic", []))

    def test_titles_carry_the_genre(self):
        epic = prose.chapter_title("epic", "the breakthrough", 1, "atlas api")
        noir = prose.chapter_title("noir", "the breakthrough", 1, "atlas api")
        self.assertEqual("Atlas API, or The Breakthrough", epic)
        self.assertEqual("The Breakthrough, Atlas API", noir)


class Stiffness(unittest.TestCase):
    """Guards against the chapter drifting back into a changelog."""

    def setUp(self):
        self.epic = prose.offline_chapter("epic", WEEK, "atlas api")
        self.noir = prose.offline_chapter("noir", WEEK, "atlas api")

    def test_every_sentence_is_cited_on_a_full_week(self):
        for body in (self.epic, self.noir):
            result = canon.verify(body, WEEK_IDS, WEEK_BY_ID)
            self.assertGreater(result["sentences_total"], 0)
            self.assertEqual(
                result["sentences_verified"], result["sentences_total"], result["cut"]
            )

    def test_the_two_genres_barely_share_a_sentence(self):
        epic = set(canon.sentences(self.epic))
        noir = set(canon.sentences(self.noir))
        shared = len(epic & noir)
        self.assertGreater(len(epic), 4)
        self.assertLessEqual(
            shared / len(epic), 0.4, f"{shared} of {len(epic)} sentences are identical"
        )

    def test_filenames_do_not_dominate(self):
        sentences = canon.sentences(self.epic)
        named = [
            sentence
            for sentence in sentences
            if re.search(r"[A-Za-z0-9_\-]+\.(py|md|ts|tf|json)", sentence) or "C:/" in sentence
        ]
        self.assertLessEqual(len(named), max(1, len(sentences) // 3), named)

    def test_a_frame_tail_is_not_reused_to_death(self):
        tails = []
        for sentence in canon.sentences(self.epic):
            tails.append(sentence.split(",")[-1].strip())
        if tails:
            worst = max(tails.count(tail) for tail in tails)
            self.assertLessEqual(worst, 2, tails)


if __name__ == "__main__":
    unittest.main()
