"""The ledger connection must follow the profile it is serving."""

import threading
import unittest
from unittest import mock

from imprint_plugin import capture, db


class ConnectionScope(unittest.TestCase):
    def setUp(self):
        self.opened = []
        self._connect = mock.patch.object(db, "connect", side_effect=self._fake_connect)
        self._connect.start()
        capture._local = threading.local()

    def _fake_connect(self, path=None):
        connection = mock.Mock(name=f"conn-{len(self.opened)}")
        self.opened.append(connection)
        return connection

    def tearDown(self):
        self._connect.stop()
        capture._local = threading.local()

    def test_same_profile_reuses_one_connection(self):
        with mock.patch.object(db, "active_home", return_value="/profiles/a"):
            first = capture._conn()
            second = capture._conn()

        self.assertIs(first, second)
        self.assertEqual(1, len(self.opened))

    def test_a_profile_switch_reopens_the_ledger(self):
        """A thread that moves from profile A to B must not keep writing to A."""
        with mock.patch.object(db, "active_home", return_value="/profiles/a"):
            first = capture._conn()
        with mock.patch.object(db, "active_home", return_value="/profiles/b"):
            second = capture._conn()

        self.assertIsNot(first, second)
        self.assertEqual(2, len(self.opened))
        first.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
