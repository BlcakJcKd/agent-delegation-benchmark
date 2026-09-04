import unittest

from benchmark.edit_scope import matches_edit_scope, normalize_relative_path


class EditScopeTests(unittest.TestCase):
    def test_recursive_pattern_matches_direct_and_nested_children(self):
        pattern = ("inventory/**/*.py",)
        self.assertTrue(matches_edit_scope("inventory/api.py", pattern))
        self.assertTrue(matches_edit_scope("inventory/foo/api.py", pattern))
        self.assertTrue(matches_edit_scope("inventory/foo/bar/api.py", pattern))

    def test_recursive_pattern_rejects_unrelated_and_wrong_extension(self):
        pattern = ("inventory/**/*.py",)
        self.assertFalse(matches_edit_scope("tests/api.py", pattern))
        self.assertFalse(matches_edit_scope("inventory/api.json", pattern))

    def test_exact_and_single_level_patterns(self):
        self.assertTrue(matches_edit_scope("README.md", ("README.md",)))
        self.assertTrue(matches_edit_scope("inventory/api.py", ("inventory/*.py",)))
        self.assertFalse(matches_edit_scope("inventory/nested/api.py", ("inventory/*.py",)))
        self.assertTrue(matches_edit_scope("inventory/a.py", ("inventory/?.py",)))
        self.assertFalse(matches_edit_scope("inventory/ab.py", ("inventory/?.py",)))

    def test_normalization_is_deterministic_and_rejects_escape_paths(self):
        self.assertEqual(normalize_relative_path("inventory\\./api.py"), ("inventory", "api.py"))
        for path in ("../secret", "inventory/../../secret", "/etc/passwd", "C:/secret", ""):
            self.assertIsNone(normalize_relative_path(path))
            self.assertFalse(matches_edit_scope(path, ("**",)))

    def test_patterns_are_or_combined(self):
        self.assertTrue(matches_edit_scope("src/a.py", ("docs/**", "src/**/*.py")))
        self.assertTrue(matches_edit_scope("docs/index.md", ("docs/**", "src/**/*.py")))
        self.assertFalse(matches_edit_scope("data/a.csv", ("docs/**", "src/**/*.py")))


if __name__ == "__main__":
    unittest.main()
