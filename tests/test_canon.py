"""The canon checker: false claims are cut, true claims survive."""

import unittest

from imprint_plugin import canon

EVENTS = {
    "e1": {
        "kind": "tool",
        "tool": "shell",
        "target": "C:/work/imprint-plugin",
        "action": "exec",
        "outcome": "ok",
        "summary": "3 retries then success",
        "error_sig": None,
    },
    "e2": {
        "kind": "tool",
        "tool": "write_file",
        "target": "C:/work/imprint-plugin/typeset/book.typ",
        "action": "write",
        "outcome": "ok",
        "summary": "wrote the book template",
        "error_sig": None,
    },
}
ALLOWED = set(EVENTS)


class Deterministic(unittest.TestCase):
    def test_supported_sentence_survives(self):
        finding = canon.check_sentence("It took 3 retries [e1].", ALLOWED, EVENTS)
        self.assertTrue(finding["ok"], finding["reasons"])

    def test_invented_number_is_rejected(self):
        finding = canon.check_sentence("It took 9 retries [e1].", ALLOWED, EVENTS)
        self.assertFalse(finding["ok"])
        self.assertTrue(any("9" in reason for reason in finding["reasons"]))

    def test_uncited_sentence_is_rejected(self):
        finding = canon.check_sentence("The build worked.", ALLOWED, EVENTS)
        self.assertFalse(finding["ok"])
        self.assertIn("no citation", finding["reasons"])

    def test_unknown_citation_is_rejected(self):
        finding = canon.check_sentence("The build worked [e99].", ALLOWED, EVENTS)
        self.assertFalse(finding["ok"])

    def test_foreign_citation_is_rejected(self):
        finding = canon.check_sentence("The build worked [e2].", {"e1"}, EVENTS)
        self.assertFalse(finding["ok"])

    def test_invented_entity_is_rejected(self):
        finding = canon.check_sentence(
            "The PaymentGatewayService approved it [e1].", ALLOWED, EVENTS
        )
        self.assertFalse(finding["ok"])

    def test_real_path_is_accepted(self):
        finding = canon.check_sentence(
            "The template went to C:/work/imprint-plugin/typeset/book.typ [e2].",
            ALLOWED,
            EVENTS,
        )
        self.assertTrue(finding["ok"], finding["reasons"])

    def test_sentence_starting_with_a_capital_is_fine(self):
        finding = canon.check_sentence("It worked [e1].", ALLOWED, EVENTS)
        self.assertTrue(finding["ok"], finding["reasons"])


class Disposition(unittest.TestCase):
    def test_injected_false_claim_is_cut(self):
        body = "It took 3 retries [e1]. It took 9 retries [e1]."
        result = canon.verify(body, ALLOWED, EVENTS)
        self.assertEqual(2, result["sentences_total"])
        self.assertEqual(1, result["sentences_verified"])
        self.assertEqual(1, len(result["cut"]))
        self.assertNotIn("9 retries", result["body"])

    def test_true_claim_survives(self):
        body = "It took 3 retries [e1]."
        result = canon.verify(body, ALLOWED, EVENTS)
        self.assertEqual(1, result["sentences_verified"])
        self.assertEqual([], result["cut"])

    def test_ratio_is_honest(self):
        body = "It took 3 retries [e1]. It took 9 retries [e1]."
        result = canon.verify(body, ALLOWED, EVENTS)
        self.assertAlmostEqual(0.5, result["verified_ratio"], places=3)

    def test_empty_body_has_zero_ratio(self):
        result = canon.verify("", ALLOWED, EVENTS)
        self.assertEqual(0, result["sentences_total"])
        self.assertEqual(0.0, result["verified_ratio"])

    def test_semantic_pass_can_cut_a_supported_claim(self):
        def ask(prompt):
            return '{"verdicts":[{"i":0,"verdict":"unrelated"}]}'

        result = canon.verify("It took 3 retries [e1].", ALLOWED, EVENTS, ask=ask)
        self.assertEqual(0, result["sentences_verified"])
        self.assertTrue(result["semantic_pass"])

    def test_semantic_failure_fails_open_not_closed(self):
        def ask(prompt):
            raise RuntimeError("provider down")

        result = canon.verify("It took 3 retries [e1].", ALLOWED, EVENTS, ask=ask)
        self.assertEqual(1, result["sentences_verified"])


class Sentences(unittest.TestCase):
    def test_citations_are_not_split(self):
        parts = canon.sentences("One thing [e1]. Another thing [e2].")
        self.assertEqual(2, len(parts))

    def test_cited_ids(self):
        self.assertEqual(["e1", "e2"], canon.cited_ids("A [e1] and b [e2]."))


if __name__ == "__main__":
    unittest.main()
