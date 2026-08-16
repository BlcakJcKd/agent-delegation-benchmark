import argparse
import json
import shutil
import sys
import unittest
from pathlib import Path

from benchmark.adapters import Adapter
from benchmark.runner import (
    _blocking_permission_denial,
    _parse_task_agents,
    _selection,
    _tier_or_custom_adapters,
    execute,
    prepare,
    randomized_execution_order,
)
from benchmark.tasks import repository_root
from benchmark.tiers import TIERS


def _copy_frozen_material(destination: Path) -> None:
    source = repository_root()
    shutil.copytree(source / "fixtures", destination / "fixtures")
    shutil.copytree(source / "tasks", destination / "tasks")
    shutil.copy2(source / "fixtures.lock.json", destination / "fixtures.lock.json")
    (destination / "private_admin/manifests").mkdir(parents=True)
    shutil.copy2(source / "private_admin/manifests/repository_review.json", destination / "private_admin/manifests/repository_review.json")


class _FakeAdapter(Adapter):
    name = "fake"

    @property
    def executable(self):
        return sys.executable

    def availability(self):
        return True, sys.executable

    def command(self, workspace, prompt, output_dir, task_id=None):
        script = "import json; print(json.dumps({'usage': {'input_tokens': 7}})); open('answer.json','w').write(json.dumps({'n':12,'mean_response':15.25,'control_mean':12.0,'treatment_mean':18.5,'difference':6.5}))"
        return [sys.executable, "-c", script]


class _MalformedOutputAdapter(Adapter):
    name = "malformed"

    @property
    def executable(self):
        return sys.executable

    def availability(self):
        return True, sys.executable

    def command(self, workspace, prompt, output_dir, task_id=None):
        return [sys.executable, "-c", "print('not-json')"]


class RunnerTests(unittest.TestCase):
    def test_prepare_makes_equal_isolated_workspaces(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            _copy_frozen_material(root)
            run_root = prepare("isolation", ["research_python"], ["codex", "claude"], root)
            codex = run_root / "research_python/codex/workspace"
            claude = run_root / "research_python/claude/workspace"
            self.assertEqual((codex / "TASK.md").read_text(), (claude / "TASK.md").read_text())
            self.assertEqual((codex / "data/observations.csv").read_bytes(), (claude / "data/observations.csv").read_bytes())
            (codex / "local-only.txt").write_text("changed")
            self.assertFalse((claude / "local-only.txt").exists())

    def test_prepare_records_named_tier_metadata(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            _copy_frozen_material(root)
            tier = TIERS["tier-a-medium"]
            run_root = prepare(
                "tier-metadata", ["research_python"], ["codex", "claude", "agy"], root,
                tier=tier, requested_configuration={"codex": {"requested_model": "gpt-5.6-terra"}},
            )
            metadata = json.loads((run_root / "run.json").read_text())
            self.assertEqual(metadata["benchmark_tier"], "tier-a-medium")
            self.assertEqual(metadata["tier_configuration"]["models"], tier.models)
            self.assertEqual(metadata["requested_configuration"]["codex"]["requested_model"], "gpt-5.6-terra")

    def test_partial_tier_prepare_records_canonical_tier_and_subset(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            _copy_frozen_material(root)
            tier = TIERS["tier-b-cheap"]
            run_root = prepare(
                "tier-subset-metadata", ["research_python"], ["agy"], root,
                tier=tier,
                requested_configuration={"agy": {"requested_model": tier.models["agy"]}},
            )
            metadata = json.loads((run_root / "run.json").read_text())
            self.assertEqual(metadata["benchmark_tier"], "tier-b-cheap")
            self.assertEqual(metadata["tier_agents_available"], ["agy", "claude", "codex"])
            self.assertEqual(metadata["agents_requested"], ["agy"])
            self.assertEqual(metadata["tier_execution_scope"], "partial")
            self.assertEqual(metadata["requested_configuration"]["agy"]["requested_model"], "gemini-3.7-flash-medium")

    def test_prepare_records_explicit_crossover_provenance(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            _copy_frozen_material(root)
            run_root = prepare(
                "crossover-metadata", ["scientific_writing"], ["agy"], root,
                tier=TIERS["tier-b-cheap"],
                run_context={
                    "crossover": "gemini-flash-vs-tier-a",
                    "source_tier_reference": "tier-a-medium",
                },
            )
            metadata = json.loads((run_root / "run.json").read_text())
            self.assertEqual(metadata["crossover"], "gemini-flash-vs-tier-a")
            self.assertEqual(metadata["source_tier_reference"], "tier-a-medium")

    def test_named_tier_accepts_nonempty_agent_subsets_with_tier_models(self):
        parser = argparse.ArgumentParser()
        expected = {
            ("agy",): {"agy": "gemini-3.7-flash-medium"},
            ("codex",): {"codex": "gpt-5.6-luna"},
            ("claude",): {"claude": "claude-haiku-4-5-20251001"},
            ("codex", "agy"): {"codex": "gpt-5.6-luna", "agy": "gemini-3.7-flash-medium"},
            ("codex", "claude", "agy"): {
                "codex": "gpt-5.6-luna",
                "claude": "claude-haiku-4-5-20251001",
                "agy": "gemini-3.7-flash-medium",
            },
        }
        for agents, models in expected.items():
            args = argparse.Namespace(
                tier="tier-b-cheap", models=None,
                codex_reasoning_effort=None, claude_reasoning_effort=None,
            )
            adapters, errors, tier = _tier_or_custom_adapters(args, list(agents), parser)
            self.assertEqual(errors, [])
            self.assertEqual(tier.id, "tier-b-cheap")
            for agent, model in models.items():
                self.assertEqual(adapters[agent].model, model)
            if "codex" in models:
                self.assertEqual(adapters["codex"].reasoning_effort, "medium")
            if "claude" in models:
                self.assertEqual(adapters["claude"].reasoning_effort, "medium")

    def test_named_tier_rejects_unknown_agents_and_configuration_overrides(self):
        parser = argparse.ArgumentParser()
        unknown = argparse.Namespace(
            tier="tier-b-cheap", models=None,
            codex_reasoning_effort=None, claude_reasoning_effort=None,
        )
        with self.assertRaises(SystemExit):
            _tier_or_custom_adapters(unknown, ["unknown"], parser)
        conflicting_model = argparse.Namespace(
            tier="tier-b-cheap", models="agy=another-model",
            codex_reasoning_effort=None, claude_reasoning_effort=None,
        )
        with self.assertRaises(SystemExit):
            _tier_or_custom_adapters(conflicting_model, ["agy"], parser)
        conflicting_effort = argparse.Namespace(
            tier="tier-b-cheap", models=None,
            codex_reasoning_effort="high", claude_reasoning_effort=None,
        )
        with self.assertRaises(SystemExit):
            _tier_or_custom_adapters(conflicting_effort, ["codex"], parser)

    def test_selection_rejects_empty_or_unknown_agents(self):
        parser = argparse.ArgumentParser()
        with self.assertRaises(SystemExit):
            _selection(argparse.Namespace(agents="", tasks="research_python"), parser)
        with self.assertRaises(SystemExit):
            _selection(argparse.Namespace(agents="unknown", tasks="research_python"), parser)

    def test_task_agent_mapping_prepares_only_missing_pairs_and_records_plan(self):
        parser = argparse.ArgumentParser()
        mapping = _parse_task_agents(
            "diagnostic_plot=claude,agy;debug_package=codex,claude,agy",
            ["diagnostic_plot", "debug_package"], ["codex", "claude", "agy"], parser,
        )
        self.assertEqual(mapping, {
            "diagnostic_plot": ["claude", "agy"],
            "debug_package": ["codex", "claude", "agy"],
        })
        with self.assertRaises(SystemExit):
            _parse_task_agents(
                "diagnostic_plot=claude", ["diagnostic_plot", "debug_package"],
                ["codex", "claude", "agy"], parser,
            )
        with self.assertRaises(SystemExit):
            _parse_task_agents(
                "diagnostic_plot=unknown;debug_package=codex", ["diagnostic_plot", "debug_package"],
                ["codex", "claude", "agy"], parser,
            )
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            root = Path(temp)
            _copy_frozen_material(root)
            run_root = prepare(
                "continuation", ["diagnostic_plot", "debug_package"], ["codex", "claude", "agy"], root,
                tier=TIERS["tier-b-cheap"], task_agents=mapping,
            )
            self.assertFalse((run_root / "diagnostic_plot/codex").exists())
            self.assertTrue((run_root / "diagnostic_plot/claude/workspace").exists())
            self.assertTrue((run_root / "diagnostic_plot/agy/workspace").exists())
            self.assertTrue((run_root / "debug_package/codex/workspace").exists())
            metadata = json.loads((run_root / "run.json").read_text())
            self.assertEqual(metadata["task_agents"], mapping)
            self.assertEqual(metadata["tier_execution_scope"], "partial")

    def test_randomized_orders_are_recordable_and_not_fixed(self):
        tasks = ["research_python", "repository_review", "diagnostic_plot"]
        orders = randomized_execution_order(tasks, ["codex", "claude", "agy"])
        self.assertEqual(set(orders), set(tasks))
        self.assertTrue(all(set(order) == {"codex", "claude", "agy"} for order in orders.values()))
        self.assertTrue(any(orders[task] != orders[tasks[0]] for task in tasks[1:]))

    def test_permission_denial_is_blocking_only_when_delivery_or_python_verification_needs_it(self):
        optional = [{"tool_name": "Bash", "tool_input": {"command": "git status --short"}}]
        verification = [{"tool_name": "Bash", "tool_input": {"command": "python analysis.py"}}]
        self.assertFalse(_blocking_permission_denial("research_python", optional, required_output_missing=False))
        self.assertTrue(_blocking_permission_denial("research_python", verification, required_output_missing=False))
        self.assertTrue(_blocking_permission_denial("research_python", optional, required_output_missing=True))

    def test_execute_records_evidence_and_blinds_submission(self):
        from tempfile import TemporaryDirectory
        import benchmark.runner as runner
        with TemporaryDirectory() as temp:
            root = Path(temp)
            _copy_frozen_material(root)
            old = runner.ADAPTERS.get("fake")
            runner.ADAPTERS["fake"] = _FakeAdapter("fake")
            try:
                self.assertEqual(execute("evidence", ["research_python"], ["fake"], root, timeout=10), 0)
            finally:
                if old is None:
                    del runner.ADAPTERS["fake"]
                else:
                    runner.ADAPTERS["fake"] = old
            result = root / "runs/evidence/research_python/fake/result"
            record = json.loads((result / "execution.json").read_text())
            self.assertEqual(record["exit_code"], 0)
            self.assertIn("answer.json", record["files_changed"])
            self.assertTrue((result / "stdout.txt").exists())
            self.assertEqual(json.loads((result / "evaluation.json").read_text())["score"], 5.0)
            blind_files = list((root / "runs/evidence/blind/research_python").iterdir())
            self.assertEqual(len(blind_files), 1)
            self.assertNotIn("fake", blind_files[0].name)

    def test_execute_returns_nonzero_for_protocol_failure_without_deliverable(self):
        from tempfile import TemporaryDirectory
        import benchmark.runner as runner
        with TemporaryDirectory() as temp:
            root = Path(temp)
            _copy_frozen_material(root)
            old = runner.ADAPTERS.get("malformed")
            runner.ADAPTERS["malformed"] = _MalformedOutputAdapter("malformed")
            try:
                self.assertEqual(execute("malformed", ["research_python"], ["malformed"], root, timeout=10), 1)
            finally:
                if old is None:
                    del runner.ADAPTERS["malformed"]
                else:
                    runner.ADAPTERS["malformed"] = old
            record = json.loads((root / "runs/malformed/research_python/malformed/result/execution.json").read_text())
            self.assertIn("expected_structured_cli_output_was_not_received", record["harness_failure_reasons"])
