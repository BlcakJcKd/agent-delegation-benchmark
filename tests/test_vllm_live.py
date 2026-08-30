"""Hermetic tests for GET-only vLLM live status."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from delegation.status_cli import build_report
from delegation.vllm import inspect_vllm_live_routes, inspect_vllm_routes


MODEL = "Qwen/example-model"


def metrics(*, running=0, waiting=0, prompt=0, generation=0, requests=0, preemptions=0, kv=0):
    return f'''# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{{model_name="{MODEL}"}} {running}
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting{{model_name="{MODEL}"}} {waiting}
# TYPE vllm:kv_cache_usage_perc gauge
vllm:kv_cache_usage_perc{{model_name="{MODEL}"}} {kv}
# TYPE vllm:prompt_tokens counter
vllm:prompt_tokens_total{{model_name="{MODEL}"}} {prompt}
# TYPE vllm:generation_tokens counter
vllm:generation_tokens_total{{model_name="{MODEL}"}} {generation}
# TYPE vllm:request_success counter
vllm:request_success_total{{model_name="{MODEL}"}} {requests}
# TYPE vllm:num_preemptions counter
vllm:num_preemptions_total{{model_name="{MODEL}"}} {preemptions}
# TYPE vllm:cache_config_info gauge
vllm:cache_config_info{{enable_prefix_caching="false",model_name="{MODEL}"}} 1
# TYPE vllm:engine_sleep_state gauge
vllm:engine_sleep_state{{model_name="{MODEL}",sleep_state="awake"}} 1
'''.encode()


class FakeResponse:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return self._body


class SequenceOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.paths = []

    def __call__(self, request, timeout):
        self.paths.append((request.method, Path(request.full_url).name, timeout))
        return self.responses.pop(0)


class LiveStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.config_home = root / "config"
        config_dir = self.config_home / "agent-delegation"
        config_dir.mkdir(parents=True)
        self.vllm_path = config_dir / "vllm.toml"
        self.vllm_path.write_text(
            '[providers.lab-qwen]\nmodel = "Qwen/example-model"\n'
            'base_url = "http://vllm.example.invalid/v1"\n'
            'credential_source = "env:LAB_TOKEN"\nmax_tokens = 128\n'
        )
        self.env = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config_home)}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def route_info(self):
        return inspect_vllm_routes(self.vllm_path)

    def responses(self, first, second):
        return [
            FakeResponse(200, b'{"server_load": 0}'), FakeResponse(200, metrics(**first)),
            FakeResponse(200, b'{"server_load": 0}'), FakeResponse(200, metrics(**second)),
        ]

    def test_idle_status_uses_two_get_snapshots_and_no_inference_endpoint(self):
        opener = SequenceOpener(self.responses({}, {}))
        result = inspect_vllm_live_routes(self.route_info(), opener=opener, sleep=lambda _: None)
        live = result["lab-qwen"]
        self.assertEqual(live.state, "IDLE")
        self.assertEqual(live.recent_requests, 0)
        self.assertFalse(live.prefix_caching)
        self.assertEqual(live.engine_sleep_state, "awake")
        self.assertEqual([path for _method, path, _timeout in opener.paths], ["load", "metrics", "load", "metrics"])

    def test_activity_is_active_when_running_or_recent_counters_increase(self):
        opener = SequenceOpener(self.responses({}, {"running": 1, "prompt": 4, "generation": 2, "requests": 1}))
        live = inspect_vllm_live_routes(self.route_info(), opener=opener, sleep=lambda _: None)["lab-qwen"]
        self.assertEqual(live.state, "ACTIVE")
        self.assertEqual(live.recent_requests, 1)
        self.assertEqual(live.recent_prompt_tokens, 4)
        self.assertEqual(live.recent_generation_tokens, 2)

    def test_waiting_and_preemption_are_pressure_states(self):
        opener = SequenceOpener(self.responses({}, {"waiting": 1}))
        live = inspect_vllm_live_routes(self.route_info(), opener=opener, sleep=lambda _: None)["lab-qwen"]
        self.assertEqual(live.state, "PRESSURED")
        opener = SequenceOpener(self.responses({}, {"preemptions": 1}))
        live = inspect_vllm_live_routes(self.route_info(), opener=opener, sleep=lambda _: None)["lab-qwen"]
        self.assertEqual(live.state, "PRESSURED")

    def test_missing_scheduler_metrics_are_unknown(self):
        body = b'# TYPE vllm:request_success counter\nvllm:request_success_total 1\n'
        opener = SequenceOpener([
            FakeResponse(200, b'{"server_load": 0}'), FakeResponse(200, body),
            FakeResponse(200, b'{"server_load": 0}'), FakeResponse(200, body),
        ])
        live = inspect_vllm_live_routes(self.route_info(), opener=opener, sleep=lambda _: None)["lab-qwen"]
        self.assertEqual(live.state, "UNKNOWN")

    def test_observability_auth_failure_is_unknown_without_credential_lookup(self):
        opener = SequenceOpener([FakeResponse(401, b"private"), FakeResponse(401, b"private")])
        with patch("delegation.vllm._resolve_credential", side_effect=AssertionError("credential lookup")):
            live = inspect_vllm_live_routes(self.route_info(), opener=opener, sleep=lambda _: None)["lab-qwen"]
        self.assertEqual(live.state, "UNKNOWN")
        self.assertIn("authentication", live.reason)

    def test_build_report_live_status_is_optional_and_machine_readable(self):
        opener = SequenceOpener(self.responses({}, {}))
        with patch("delegation.vllm.urllib.request.urlopen", opener):
            report = build_report("manual", live=True)
        self.assertEqual(report["live_vllm"]["lab-qwen"]["state"], "IDLE")


if __name__ == "__main__":
    unittest.main()
