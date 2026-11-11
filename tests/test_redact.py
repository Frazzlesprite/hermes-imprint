"""Redaction is the boundary between a useful ledger and a leak."""

import unittest

from imprint_plugin import redact


class RedactSecrets(unittest.TestCase):
    def test_openai_key_is_removed(self):
        clean, kinds = redact.redact("key sk-abcdef0123456789abcdef0123456789 here")
        self.assertNotIn("sk-abc", clean)
        self.assertIn("openai_key", kinds)

    def test_github_token_is_removed(self):
        clean, kinds = redact.redact("token ghp_0123456789abcdefghijABCDEFGHIJ012345")
        self.assertNotIn("ghp_", clean)
        self.assertIn("github_token", kinds)

    def test_password_assignment_is_removed(self):
        clean, kinds = redact.redact('password="hunter2hunter2"')
        self.assertNotIn("hunter2", clean)
        self.assertIn("assignment", kinds)

    def test_url_credentials_are_removed(self):
        clean, _ = redact.redact("https://alice:s3cret@example.com/repo.git")
        self.assertNotIn("s3cret", clean)
        self.assertIn("example.com", clean)

    def test_private_key_block_is_removed(self):
        block = (
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"
        )
        clean, kinds = redact.redact(block)
        self.assertNotIn("MIIEow", clean)
        self.assertIn("private_key", kinds)

    def test_plain_text_survives(self):
        clean, kinds = redact.redact("edited capture.py and ran the tests")
        self.assertEqual("edited capture.py and ran the tests", clean)
        self.assertEqual((), kinds)


class Summarize(unittest.TestCase):
    def test_truncates_at_a_word_boundary(self):
        summary, _ = redact.summarize("word " * 200)
        self.assertLessEqual(len(summary), redact.SUMMARY_LIMIT)
        self.assertTrue(summary.endswith("\u2026"))

    def test_short_text_is_untouched(self):
        summary, kinds = redact.summarize("a short summary")
        self.assertEqual("a short summary", summary)
        self.assertEqual((), kinds)

    def test_collapses_newlines(self):
        summary, _ = redact.summarize("line one\nline two\tline three")
        self.assertEqual("line one line two line three", summary)


class ErrorSignature(unittest.TestCase):
    def test_same_failure_same_signature(self):
        first = redact.error_signature(
            "FileNotFoundError: [Errno 2] No such file or directory: 'C:\\a\\b.py'"
        )
        second = redact.error_signature(
            "FileNotFoundError: [Errno 2] No such file or directory: 'C:\\x\\y.py'"
        )
        self.assertEqual(first, second)

    def test_signature_is_bounded(self):
        signature = redact.error_signature("boom " * 200)
        self.assertLessEqual(len(signature), 121)


class Exclusions(unittest.TestCase):
    def test_case_and_separator_insensitive(self):
        patterns = ["C:\\Secret"]
        self.assertTrue(redact.is_excluded("c:/secret/notes.md", patterns))

    def test_nested_path_is_excluded(self):
        self.assertTrue(redact.is_excluded("C:/Secret/a/b/c.txt", ["C:/Secret"]))

    def test_sibling_path_is_not_excluded(self):
        self.assertFalse(redact.is_excluded("C:/Secrets/a.txt", ["C:/Secret"]))

    def test_glob_pattern(self):
        self.assertTrue(redact.is_excluded("C:/work/tmp/x.log", ["C:/work/tmp/*"]))


if __name__ == "__main__":
    unittest.main()
