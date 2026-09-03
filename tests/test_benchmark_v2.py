import json
import tempfile
import unittest
from pathlib import Path

from benchmark.v2.evaluate import evaluate, reference_fix
from benchmark.v2.generate import make_instance, materialize, workspace_digest
from benchmark.v2.reasoning import CASES, score
from benchmark.v2.telemetry import parse_trace
from benchmark.v2.validate import validate


class V2GenerationTests(unittest.TestCase):
    def test_validation_gate(self):
        result = validate(Path.cwd(), 8100)
        self.assertTrue(result["ok"], result)

    def test_reproducible_candidate(self):
        i = make_instance("C1_config_precedence", 12)
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            materialize(i, a); materialize(i, b)
            self.assertEqual(workspace_digest(a), workspace_digest(b))

    def test_hidden_evaluator_not_in_candidate(self):
        i = make_instance("C7_diagnostic_artifact", 12)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "candidate"; materialize(i, p)
            self.assertFalse(any("evaluate" in x.name or "generator" in x.name for x in p.rglob("*")))


class V2TelemetryTests(unittest.TestCase):
    def test_jsonl_usage_and_tool_error(self):
        trace = "\n".join([
            json.dumps({"type":"message", "responseId":"r1", "model":"m", "provider":"p", "usage":{"prompt_tokens":10,"completion_tokens":4}, "message":{"role":"assistant","content":[{"type":"text","text":"go"},{"type":"thinking","thinking":"hidden"}]}}),
            json.dumps({"type":"toolCall", "responseId":"r1", "toolCall":{"name":"edit","arguments":{"path":"x"}}}),
            json.dumps({"type":"tool_error", "responseId":"r1", "tool_call":{"name":"edit","arguments":{"path":"x"}}, "error":"bad"}),
            json.dumps({"type":"message", "responseId":"r1", "message":{"content":"done"}, "stop_reason":"end"}),
        ])
        items = parse_trace(trace)
        self.assertEqual(len(items), 1); self.assertEqual(items[0].input_tokens, 10); self.assertEqual(items[0].tool_calls, 2); self.assertEqual(items[0].tool_errors, 1); self.assertEqual(items[0].final_answer, "godone")


class V2ReasoningTests(unittest.TestCase):
    def test_cases_and_rubric(self):
        self.assertEqual(len(CASES), 3)
        self.assertGreaterEqual(score("R1_seed_instability", "The outlier is unstable; we cannot claim a robust improvement. Use paired per-seed analysis and bootstrap sensitivity follow-up." )["score"], 3)
