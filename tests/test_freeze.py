import unittest

from benchmark.freeze import verify_lock


class FreezeTests(unittest.TestCase):
    def test_committed_fixtures_match_the_lock(self):
        self.assertEqual(verify_lock(), [])
