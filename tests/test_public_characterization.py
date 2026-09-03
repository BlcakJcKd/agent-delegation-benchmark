import tempfile
import unittest
from pathlib import Path

from benchmark.adapters import AntigravityAdapter
from benchmark.public_characterization.evaluate import evaluate
from benchmark.public_characterization.generate import make_instance, manifest, materialize, workspace_digest
from benchmark.public_characterization.runner import check_local_suite
from ekalavya.catalogue import canonicalize_gemini_flash_generations, expand_runtime_variants
from ekalavya.harness_registry import current_registry, validate_registry
from ekalavya.schema import CandidateIdentity, RunIntent
from ekalavya.resolver import resolve


class PublicCharacterizationTests(unittest.TestCase):
    def test_instances_are_deterministic_and_have_no_authoritative_repair(self):
        first = make_instance("P1_multi_file_debug", 42)
        second = make_instance("P1_multi_file_debug", 42)
        self.assertEqual(first.files, second.files)
        self.assertEqual(first.prompt, second.prompt)
        self.assertNotIn("reference", "\n".join(first.files))
        with tempfile.TemporaryDirectory() as temp:
            a, b = Path(temp) / "a", Path(temp) / "b"
            materialize(first, a); materialize(second, b)
            self.assertEqual(workspace_digest(a), workspace_digest(b))
            assessment = evaluate(first, a)
            self.assertTrue(assessment["objective"])
            self.assertFalse(assessment["adversarial_isolation"])
            self.assertFalse(assessment["authoritative_reference_present"])
            self.assertEqual(len(assessment["checks"]), 8)
            self.assertLess(assessment["score"], 100)

    def test_manifest_records_public_identity_hashes(self):
        item = make_instance("P4_compat_refactor", 44)
        data = manifest([item])
        self.assertEqual(data["evaluation_class"], "public_characterization")
        record = data["instances"][0]
        self.assertEqual(record["task_id"], item.task_id)
        self.assertEqual(len(record["workspace_hash"]), 64)
        self.assertEqual(len(record["visible_evaluator_hash"]), 64)

    def test_local_fixture_check_is_repeatable(self):
        self.assertEqual(check_local_suite(), check_local_suite())

    def test_exact_runtime_model_id_is_selected_without_reasoning_overlay(self):
        for model_id in ("gemini-3.7-flash-low", "gemini-3.7-flash-medium", "gemini-3.7-flash-high", "gemini-3.8-flash-low", "gemini-3.8-flash-medium", "gemini-3.8-flash-high"):
            argv = AntigravityAdapter(model=model_id, reasoning_effort=None).command(Path("/workspace"), "prompt", Path("/evidence"))
            self.assertEqual(argv[argv.index("--model") + 1], model_id)
            self.assertNotIn("--effort", argv)

    def test_catalogue_lifecycle_is_generation_level_and_variants_are_exact(self):
        observed = "2026-09-03T12:00:00+00:00"
        discovered = [{"provider_model_id": f"gemini-{generation}-flash-{reasoning}", "display_name": f"Gemini {generation} {reasoning}"} for generation in ("3.6", "3.7", "3.8") for reasoning in ("low", "medium", "high")]
        entries = canonicalize_gemini_flash_generations([], discovered, observed_at=observed, serving_engine_version="1.1.25")
        self.assertEqual({(item["generation"], item["lifecycle"], item["lifecycle_scope"]) for item in entries}, {("3.6", "previous", "generation_family"), ("3.7", "current", "generation_family"), ("3.8", "candidate", "generation_family")})
        self.assertTrue(all(item["discovery_timestamp"] == observed for item in entries))
        variants = expand_runtime_variants(entries)
        ids = {item["provider_model_id"] for item in variants if item.get("catalogue_parent_identity_key")}
        self.assertIn("gemini-3.8-flash-high", ids)
        current = next(item for item in entries if item["generation"] == "3.7")
        profile = {"default_identity_key": current["identity_key"], "permitted_candidates": [current["identity_key"]], "reasoning_policy": "overrideable", "default_reasoning": "medium"}
        result = resolve(RunIntent("flash", provider="gemini", reasoning="high"), profile, entries)
        self.assertEqual(result.state, "resolved")
        self.assertEqual(result.candidate.provider_model_id, "gemini-3.7-flash-high")


class HarnessRegistryTests(unittest.TestCase):
    def test_registry_has_separate_eligibility_classes(self):
        registry = current_registry()
        validate_registry(registry)
        agy = next(item for item in registry if item["name"] == "agy")
        self.assertEqual(agy["eligibility"]["ordinary"], "supported")
        self.assertEqual(agy["eligibility"]["public_characterization"], "supported")
        self.assertEqual(agy["eligibility"]["hidden_benchmark"], "unsupported")
        self.assertIn("independent candidate-tool subprocess", agy["reason"])


if __name__ == "__main__":
    unittest.main()
