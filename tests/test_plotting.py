import tempfile
import unittest
from pathlib import Path

from benchmark.v2.plotting import plot_rows


class LedgerPlottingTests(unittest.TestCase):
    def test_zero_rows_are_skipped_without_creating_png(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "plot.png"
            result = plot_rows([], path, x_key="x", y_key="y", xlabel="x", ylabel="y")
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "no_valid_observations")
            self.assertFalse(path.exists())

    def test_all_invalidated_rows_are_skipped_without_creating_png(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "plot.png"
            rows = [{"x": 1, "y": 2, "status": "invalidated"}, {"x": 2, "y": 3, "valid": False}]
            result = plot_rows(rows, path, x_key="x", y_key="y", xlabel="x", ylabel="y")
            self.assertEqual(result, {"status": "skipped", "reason": "no_valid_observations", "path": None})
            self.assertFalse(path.exists())

    def test_valid_rows_create_a_plot(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "plot.png"
            result = plot_rows([{"x": 1, "y": 2}, {"x": 2, "y": 3}], path, x_key="x", y_key="y", xlabel="x", ylabel="y")
            self.assertEqual(result["status"], "created")
            self.assertEqual(result["observations"], 2)
            self.assertTrue(path.is_file())
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
