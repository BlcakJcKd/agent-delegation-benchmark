"""Deterministic Benchmark V2 task generation.

Only candidate source/tests/prompts are written to a candidate directory.
Evaluator metadata and seed remain controller-side objects.
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import CODING_FAMILIES, SCHEMA_VERSION


@dataclass(frozen=True)
class TaskInstance:
    family: str
    seed: int
    prompt: str
    evaluator_key: str
    variant: dict[str, object]

    @property
    def task_id(self) -> str:
        return f"{self.family}@{self.seed}"


def _write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _variant(seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    return {"port": rng.choice([7311, 8422, 9134]), "window": rng.choice([3, 4, 5]), "suffix": rng.choice(["_v", "_next", "_alt"]), "limit": rng.choice([7, 9, 11])}


def _common_readme(title: str, detail: str) -> str:
    return f"""# {title}\n\n{detail}\n\nWork only in this workspace. Do not access parent directories, hidden evaluator files, the network, or benchmark source. Preserve public APIs and add focused tests where useful.\n"""


def _c1(v: dict[str, object]) -> tuple[dict[str, str], str]:
    files = {
        "app/__init__.py": "from .config import load_settings\n__all__ = ['load_settings']\n",
        "app/config.py": """
        from .sources import defaults, read_file, read_env, parse_cli

        def load_settings(config_path=None, environ=None, argv=None):
            # The public API accepts a positional path and injectable sources.
            result = defaults()
            result.update(read_env(environ))
            result.update(read_file(config_path))
            result.update(parse_cli(argv))
            return result
        """,
        "app/sources.py": """
        import json

        KEYS = ('host', 'port', 'debug', 'retries', 'label')

        def _coerce(key, value):
            if value is None: return None
            if key in {'port', 'retries'}: return int(value)
            if key == 'debug': return str(value).lower() in {'1', 'true', 'yes', 'on'}
            return str(value)

        def defaults():
            return {'host': '127.0.0.1', 'port': 8000, 'debug': False, 'retries': 2, 'label': None}

        def read_file(path):
            if not path: return {}
            data = json.loads(open(path, encoding='utf-8').read())
            return {k: _coerce(k, data[k]) for k in KEYS if k in data}

        def read_env(environ=None):
            env = environ or {}
            mapping = {'APP_HOST': 'host', 'APP_PORT': 'port', 'APP_DEBUG': 'debug', 'APP_RETRIES': 'retries', 'APP_LABEL': 'label'}
            return {_key: _coerce(_key, env[name]) for name, _key in mapping.items() if name in env}

        def parse_cli(argv=None):
            values = {}
            for item in argv or []:
                if item.startswith('--') and '=' in item:
                    key, value = item[2:].split('=', 1)
                    if key in KEYS: values[key] = _coerce(key, value)
            return values
        """,
        "tests/test_public.py": """
        import unittest
        from app.config import load_settings

        class PublicConfigTests(unittest.TestCase):
            def test_defaults(self): self.assertEqual(load_settings()['port'], 8000)
            def test_cli_override(self): self.assertEqual(load_settings(argv=['--port=9123'])['port'], 9123)

        if __name__ == '__main__': unittest.main()
        """,
        "README.md": _common_readme("Configuration loader", "Repair precedence across defaults, JSON config, environment abstraction, and CLI overrides. Coerce typed values and preserve the load_settings public API. The visible test covers only defaults and one CLI case."),
    }
    return files, "Fix the multi-file configuration loader. Correct precedence is defaults < config file < environment < command line. Preserve positional config_path compatibility, type coercion, missing values, and the public API. Inspect the sources and tests; the visible tests are incomplete."


def _c2(v: dict[str, object]) -> tuple[dict[str, str], str]:
    files = {
        "state/__init__.py": "from .parser import Parser\nfrom .store import MutableStore\n",
        "state/store.py": """
        class MutableStore:
            def __init__(self, values=None): self.values = dict(values or {}); self.version = 0
            def put(self, key, value): self.values[key] = value; self.version += 1
            def get(self, key): return self.values[key]
        """,
        "state/parser.py": """
        class Parser:
            def __init__(self, store): self.store = store; self.cache = {}; self.parse_calls = 0
            def parse(self, key):
                if key in self.cache: return self.cache[key]
                self.parse_calls += 1
                value = tuple(int(x.strip()) for x in self.store.get(key).split(','))
                self.cache[key] = value
                return value
            def total(self, key): return sum(self.parse(key))
        """,
        "state/derived.py": """
        from .parser import Parser
        def derived_total(parser: Parser, key: str) -> int:
            return parser.total(key) * 2
        """,
        "tests/test_public.py": """
        import unittest
        from state.store import MutableStore
        from state.parser import Parser
        class PublicCacheTests(unittest.TestCase):
            def test_initial_parse(self):
                s=MutableStore({'a':'1,2,3'}); p=Parser(s)
                self.assertEqual(p.total('a'), 6); self.assertEqual(p.total('a'), 6)
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": _common_readme("Versioned derived state", "Repair stale parser results after a mutable store update. Keep caching enabled: repeated reads should hit the cache and parse_calls must remain bounded. Reason across store, parser, and derived layers."),
    }
    return files, "Repair cache invalidation for mutable backing state. A cached result is valid only for the store version that produced it. Preserve cache hits and the public Parser/MutableStore API; do not disable caching."


def _c3(v: dict[str, object]) -> tuple[dict[str, str], str]:
    files = {
        "service/__init__.py": "from .client import Client\nfrom .transport import FakeTransport, Timeout, PermanentFailure\n",
        "service/transport.py": """
        class Timeout(Exception): pass
        class PermanentFailure(Exception): pass
        class FakeTransport:
            def __init__(self, failures=None): self.failures=list(failures or []); self.effects=[]
            def post(self, payload, key=None):
                if self.failures:
                    outcome=self.failures.pop(0)
                    if outcome == 'timeout':
                        self.effects.append((key, dict(payload)))
                        raise Timeout('response lost')
                    if outcome == 'permanent': raise PermanentFailure('rejected')
                self.effects.append((key, dict(payload)))
                return {'ok': True, 'effect_count': len(self.effects)}
        """,
        "service/client.py": """
        from .transport import Timeout, PermanentFailure
        class Client:
            def __init__(self, transport, max_retries=2): self.transport=transport; self.max_retries=max_retries
            def create(self, payload, idempotency_key=None):
                attempts=0
                while attempts <= self.max_retries:
                    attempts += 1
                    try: return self.transport.post(payload, idempotency_key)
                    except PermanentFailure: raise
                    except Exception:
                        if attempts > self.max_retries: raise
        """,
        "service/recovery.py": """
        def classify(exc):
            return 'timeout' if exc.__class__.__name__ == 'Timeout' else 'permanent'
        """,
        "tests/test_public.py": """
        import unittest
        from service.client import Client
        from service.transport import FakeTransport
        class PublicRetryTests(unittest.TestCase):
            def test_success(self): self.assertTrue(Client(FakeTransport()).create({'x':1})['ok'])
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": _common_readme("Idempotent service client", "Repair retry classification and side-effect safety against the in-memory transport. Timeouts can represent an applied effect whose response was lost; permanent failures must not retry. Preserve the client API."),
    }
    return files, "Repair retry/idempotency semantics. Retry only retryable timeouts, distinguish permanent failure, and ensure a response-lost timeout cannot duplicate the side effect when the idempotency key is reused. Preserve Client.create."


def _c4(v: dict[str, object]) -> tuple[dict[str, str], str]:
    files = {
        "forecast/__init__.py": "from .pipeline import prepare, evaluate\n",
        "forecast/pipeline.py": """
        import numpy as np
        from .scaling import fit_scale, apply_scale
        def make_windows(values, width=3):
            x=[]; y=[]
            for i in range(len(values)-width): x.append(values[i:i+width]); y.append(values[i+width])
            return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        def prepare(values, split=0.7, width=3):
            x,y=make_windows(values,width)
            cut=max(1,int(len(values)*split))
            scale=fit_scale(values)
            return apply_scale(x,scale), y, cut, scale
        def evaluate(values, split=0.7, width=3):
            x,y,cut,scale=prepare(values,split,width)
            return {'train_shape': list(x.shape), 'eval_shape': list(x.shape), 'train_mean': float(x[:cut].mean()), 'eval_mean': float(x[cut:].mean()), 'scale_max': scale[1]}
        """,
        "forecast/scaling.py": """
        def fit_scale(values): return (min(values), max(values))
        def apply_scale(values, scale):
            low, high=scale; span=high-low or 1
            return (values-low)/span
        """,
        "forecast/split.py": """
        def split_index(n, fraction): return max(1, min(n-1, int(n*fraction)))
        """,
        "forecast/metrics.py": """
        def mse(actual, predicted): return sum((a-b)**2 for a,b in zip(actual,predicted))/len(actual)
        """,
        "tests/test_public.py": """
        import unittest
        from forecast.pipeline import make_windows
        class PublicForecastTests(unittest.TestCase):
            def test_shapes(self): self.assertEqual(make_windows([1,2,3,4,5],2)[0].shape, (3,2))
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": _common_readme("Time-series evaluation pipeline", "Repair the public pipeline without changing its API. Windows must not include future evaluation information in training; scaling must be fitted on training data only; preserve deterministic shapes and metrics."),
    }
    return files, "Repair the time-series pipeline without changing prepare/evaluate APIs. Enforce chronological train/eval separation, fit scaling only on training observations, prevent future leakage in windows, and preserve deterministic output shapes. Inspect all modules."


def _c5(v: dict[str, object]) -> tuple[dict[str, str], str]:
    files = {
        "sim/__init__.py": "from .engine import step, run\n",
        "sim/state.py": """
        from dataclasses import dataclass
        @dataclass
        class State:
            level: int=0
            energy: int=0
            total_input: int=0
            total_output: int=0
        """,
        "sim/engine.py": """
        from .state import State
        from .safety import clamp
        from .metrics import record_output
        def step(state, action, capacity=10):
            state.level = clamp(state.level + action, 0, capacity)
            state.total_input += action
            produced = record_output(state)
            state.total_output += produced
            state.energy += action
            return state
        def run(actions, capacity=10):
            s=State()
            for action in actions: step(s,action,capacity)
            return s
        """,
        "sim/safety.py": """
        def clamp(value, low, high): return min(max(value, low), high)
        """,
        "sim/metrics.py": """
        def record_output(state):
            return max(0, state.level // 2)
        """,
        "sim/controller.py": """
        def safe_action(requested, state): return max(-state.level, requested)
        """,
        "tests/test_public.py": """
        import unittest
        from sim.engine import run
        class PublicSimTests(unittest.TestCase):
            def test_bound(self): self.assertLessEqual(run([3,3,3]).level, 10)
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": _common_readme("State transition simulator", "Repair the simulation while preserving the public API. Actions, safety bounds, output accounting, and energy update have an intentional interaction bug. Check ordering, repeated steps, boundaries, and conservation rather than only aggregate plausibility."),
    }
    return files, "Repair the state-transition simulation. Determine the intended operation ordering across engine, safety, metrics, and controller. Preserve bounds, repeated-step behavior, and the accounting invariant: energy plus total_output must equal total_input after every step."


def _c6(v: dict[str, object]) -> tuple[dict[str, str], str]:
    files = {
        "compatpkg/__init__.py": "from .api import Client, make_client, encode, decode\n",
        "compatpkg/core.py": """
        class Client:
            def __init__(self, name, timeout=30): self.name=name; self.timeout=timeout
            def request(self, path, *, timeout=None): return {'name':self.name,'path':path,'timeout':self.timeout}
        def make_client(name, timeout=30): return Client(name,timeout)
        """,
        "compatpkg/serialization.py": """
        import json
        def encode(client): return json.dumps({'name':client.name,'timeout':client.timeout}, sort_keys=True)
        def decode(payload):
            data=json.loads(payload)
            return {'name': data['name'], 'timeout': data.get('timeout',30)}
        """,
        "compatpkg/api.py": """
        from .core import Client
        from .serialization import encode, decode
        def make_client(name, timeout=30): return Client(name, timeout)
        __all__=['Client','make_client','encode','decode']
        """,
        "tests/test_public.py": """
        import unittest
        from compatpkg import make_client
        class PublicCompatTests(unittest.TestCase):
            def test_legacy(self): self.assertEqual(make_client('x').request('/health')['name'],'x')
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": _common_readme("Compatible client refactor", "Refactor internals without breaking legacy imports/calls or serialized payloads. Add support for per-request timeout and preserve old decode behavior, error semantics, and focused file scope."),
    }
    return files, "Perform a backwards-compatible refactor. Preserve legacy imports, make_client positional usage, Client.request behavior, and old serialized JSON. Add a supported per-request timeout behavior and ensure decode returns a compatible Client-like result rather than breaking callers."


def _c7(v: dict[str, object]) -> tuple[dict[str, str], str]:
    outlier = int(v["limit"]) + 1
    csv_data = "sample,condition,score\n" + "\n".join([f"S{i:02d},control,{10+i/10:.1f}" for i in range(1, 7)] + [f"S{outlier:02d},treatment,99.0"]) + "\n"
    files = {
        "data/measurements.csv": csv_data,
        "analysis.py": """
        import csv, json
        from pathlib import Path
        def run(input_path='data/measurements.csv', output_png='diagnostic.png', output_json='summary.json'):
            rows=list(csv.DictReader(Path(input_path).open()))
            # Defects: wrong column and hard-coded summary make this look plausible.
            values=[float(r['score']) for r in rows if r['condition']=='control']
            summary={'mean_score':sum(values)/len(values),'outlier_sample':'S08','outlier_reason':'low_library_size'}
            Path(output_json).write_text(json.dumps(summary, sort_keys=True))
            Path(output_png).write_bytes(b'not a png')
            return summary
        if __name__ == '__main__': run()
        """,
        "plotting.py": """
        def save_plot(rows, path):
            import matplotlib.pyplot as plt
            plt.figure(figsize=(6,4)); plt.plot([r['score'] for r in rows]); plt.savefig(path); plt.close()
        """,
        "summary.py": """
        def summarize(rows):
            return {'rows':len(rows), 'columns':sorted(rows[0]) if rows else []}
        """,
        "tests/test_public.py": """
        import unittest, tempfile
        from analysis import run
        class PublicArtifactTests(unittest.TestCase):
            def test_writes(self):
                with tempfile.TemporaryDirectory() as d:
                    self.assertIn('mean_score',run('data/measurements.csv',d+'/a.png',d+'/a.json'))
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": _common_readme("Diagnostic artifact", "Inspect the synthetic CSV and repair the analysis. Produce a valid deterministic PNG and machine-readable summary using the correct data. Do not hard-code expected answers; preserve the run() API and use the supplied input path."),
    }
    return files, "Repair the diagnostic artifact pipeline. Use the supplied CSV rather than hard-coded answers, compute the required deterministic summary, and produce a valid PNG with the supplied run API. Inspect related modules and verify both artifacts."


_BUILDERS: dict[str, Callable[[dict[str, object]], tuple[dict[str, str], str]]] = {
    "C1_config_precedence": _c1, "C2_cache_invalidation": _c2, "C3_retry_idempotency": _c3,
    "C4_timeseries_leakage": _c4, "C5_state_transition": _c5, "C6_compat_refactor": _c6,
    "C7_diagnostic_artifact": _c7,
}


def make_instance(family: str, seed: int) -> TaskInstance:
    if family not in _BUILDERS: raise KeyError(family)
    variant = _variant(seed)
    files, prompt = _BUILDERS[family](variant)
    return TaskInstance(family, seed, prompt, family, variant)


def materialize(instance: TaskInstance, workspace: Path) -> Path:
    if workspace.exists(): shutil.rmtree(workspace)
    workspace.mkdir(parents=True, mode=0o700)
    files, _ = _BUILDERS[instance.family](instance.variant)
    _write(workspace, files)
    (workspace / "TASK.md").write_text(instance.prompt + "\n", encoding="utf-8")
    (workspace / ".benchmark-agent.txt").write_text("Work only in this workspace.\n", encoding="utf-8")
    for p in workspace.rglob("*"):
        if p.is_file(): p.chmod(0o600)
    return workspace


def workspace_digest(workspace: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in workspace.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.name != ".benchmark-agent.txt"):
        h.update(path.relative_to(workspace).as_posix().encode()); h.update(path.read_bytes())
    return h.hexdigest()


def manifest(instances: list[TaskInstance]) -> dict[str, object]:
    return {"schema_version": SCHEMA_VERSION, "instances": [{"family": x.family, "seed": x.seed, "task_id": x.task_id, "evaluator_key": x.evaluator_key, "variant": x.variant} for x in instances]}
