import json
import tempfile
import unittest
from pathlib import Path

from benchmark.evaluate import evaluate


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000000020001e221bc330000000049454e44ae426082"
)


class DiagnosticScorerRegressionTests(unittest.TestCase):
    def _workspace(self, root: Path) -> None:
        (root / "diagnostic.png").write_bytes(PNG_1X1)
        (root / "summary.json").write_text(json.dumps({"outlier_sample": "S08", "outlier_reason": "low_library_size"}))

    def test_normal_repository_execution(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); self._workspace(root)
            result = evaluate("diagnostic_plot", root, Path.cwd())
            self.assertEqual(result["score"], 3)

    def test_disposable_tmp_workspace(self):
        with tempfile.TemporaryDirectory(prefix="diagnostic-disposable-") as d:
            root = Path(d); self._workspace(root)
            self.assertEqual(evaluate("diagnostic_plot", root, root)["score"], 3)

    def test_namespace_like_workspace_without_tests_package(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "candidate"; root.mkdir()
            (root / "pkg").mkdir()  # deliberately no __init__.py
            self._workspace(root)
            result = evaluate("diagnostic_plot", root, root.parent)
            self.assertEqual(result["score"], 3)
