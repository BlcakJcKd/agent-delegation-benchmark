"""Deterministic public characterization fixtures.

The generated workspace contains the broken public project and visible
acceptance tests.  It contains no private evaluator or authoritative repair.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path

from . import FAMILIES, SUITE_NAME, SUITE_VERSION


@dataclass(frozen=True)
class TaskInstance:
    family: str
    seed: int
    prompt: str
    files: dict[str, str]
    variant: dict[str, int]

    @property
    def task_id(self) -> str:
        return f"{SUITE_NAME}:{self.family}@{self.seed}"


def _write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _variant(seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    return {"first": rng.choice([10, 11, 12]), "second": rng.choice([1, 2, 3]), "threshold": rng.choice([5, 7, 9])}


def _p1(v: dict[str, int]) -> tuple[dict[str, str], str]:
    files = {
        "app/__init__.py": "from .store import Store, DerivedTotals\nfrom .catalog import find, sorted_ids, summarize\n",
        "app/store.py": """
        class Store:
            def __init__(self, values=None):
                self.values = dict(values or {})
                self.version = 0
            def put(self, key, value):
                self.values[key] = value
                self.version += 1
            def get(self, key):
                return self.values[key]

        class DerivedTotals:
            def __init__(self, store):
                self.store = store
                self.cache = {}
                self.parse_calls = 0
            def total(self, key):
                if key in self.cache:
                    return self.cache[key]
                self.parse_calls += 1
                value = sum(int(part.strip()) for part in self.store.get(key).split(','))
                self.cache[key] = value
                return value
        """,
        "app/catalog.py": """
        def find(items, name):
            return [item for item in items if item['name'] == name]

        def sorted_ids(items):
            return [item['id'] for item in items]

        def summarize(items):
            return {'count': len(items), 'total': sum(float(item['amount']) for item in items)}
        """,
        "app/io.py": """
        import json
        from pathlib import Path
        def read_items(path):
            return json.loads(Path(path).read_text())
        """,
        "app/service.py": """
        from .catalog import find, sorted_ids, summarize
        from .io import read_items
        def report(path, name):
            items = read_items(path)
            return {'matches': find(items, name), 'ids': sorted_ids(items), 'summary': summarize(items)}
        """,
        "data/items.json": f'''[
          {{"id": 30, "name": "Alpha", "amount": {v["first"]}.0}},
          {{"id": 10, "name": "beta", "amount": {v["second"]}.0}},
          {{"id": 20, "name": "ALPHA", "amount": 4.0}}
        ]''',
        "tests/test_acceptance.py": """
        import unittest
        from app.store import Store, DerivedTotals
        from app.catalog import find
        class VisibleAcceptance(unittest.TestCase):
            def test_cache_and_lookup_basics(self):
                store = Store({'a': '1,2,3'}); totals = DerivedTotals(store)
                self.assertEqual(totals.total('a'), 6)
                self.assertEqual(totals.total('a'), 6)
                self.assertEqual(find([{'name': 'Alpha'}], 'Alpha'), [{'name': 'Alpha'}])
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": """
        # Inventory service
        Repair the interacting cache and catalogue defects while preserving the
        public imports. Requirements are fully specified by the visible tests:
        mutable store updates must invalidate derived totals, names are matched
        case-insensitively after whitespace normalization, IDs are ascending,
        and numeric summaries remain accurate.
        """,
    }
    return files, "Repair the multi-file inventory service. Preserve the public imports. Make versioned derived totals cache correctly, normalize names for case-insensitive lookup, return ascending IDs, and preserve accurate numeric summaries. Run all visible tests and add focused tests if useful."


def _p2(v: dict[str, int]) -> tuple[dict[str, str], str]:
    files = {
        "settings/__init__.py": "from .loader import load_settings\nfrom .state import Session\n",
        "settings/loader.py": """
        import json
        DEFAULTS = {'mode': 'safe', 'limit': 10, 'enabled': False}
        def _coerce(key, value):
            if key == 'limit': return int(value)
            if key == 'enabled': return str(value).lower() in {'1','true','yes','on'}
            return str(value)
        def load_settings(path=None, environ=None, argv=None):
            result = dict(DEFAULTS)
            env = environ or {}
            if path:
                with open(path, encoding='utf-8') as handle:
                    result.update(json.load(handle))
            result.update({_key: _coerce(_key, env[name]) for name, _key in {'APP_MODE':'mode','APP_LIMIT':'limit','APP_ENABLED':'enabled'}.items() if name in env})
            for item in argv or []:
                if item.startswith('--') and '=' in item:
                    key, value = item[2:].split('=', 1)
                    if key in result: result[key] = _coerce(key, value)
            return result
        """,
        "settings/state.py": """
        class Session:
            def __init__(self):
                self.current = None
                self._cache = {}
            def load(self, user):
                # Deliberate stale-state defect: the active object is reused
                # for a different user instead of consulting the keyed cache.
                if self.current is not None:
                    return self.current
                self.current = self._cache.setdefault(user, {'user': user, 'limit': 10})
                return self.current
            def reset(self):
                self.current = None
        """,
        "settings/cli.py": """
        from .loader import load_settings
        def effective(path=None, env=None, argv=None): return load_settings(path, env, argv)
        """,
        "settings/state_store.py": """
        class StateStore:
            def __init__(self): self.values = {}
            def put(self, key, value): self.values[key] = value
            def get(self, key, default=None): return self.values.get(key, default)
        """,
        "tests/test_acceptance.py": """
        import unittest
        from settings.loader import load_settings
        from settings.state import Session
        class VisibleAcceptance(unittest.TestCase):
            def test_defaults_and_cli(self):
                self.assertEqual(load_settings()['mode'], 'safe')
                self.assertEqual(load_settings(argv=['--limit=4'])['limit'], 4)
            def test_session_load(self):
                session = Session(); self.assertEqual(session.load('ada')['user'], 'ada')
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": """
        # Settings and session state
        Implement precedence defaults < JSON file < environment < CLI with
        typed values. Session state must not leak a cached user object into a
        different user load, and reset must clear the active session.
        """,
    }
    return files, "Repair settings and session state. Enforce defaults < JSON file < environment < CLI with type coercion. Ensure loading one user cannot return another user's cached object and reset clears active state. All requirements are represented in visible tests."


def _p3(v: dict[str, int]) -> tuple[dict[str, str], str]:
    files = {
        "pipeline/__init__.py": "from .core import load_rows, split_by_group, summarize\n",
        "pipeline/core.py": """
        import csv
        import random
        from pathlib import Path
        def load_rows(path):
            with Path(path).open(newline='') as handle:
                return list(csv.DictReader(handle))
        def split_by_group(rows, train_fraction=0.5):
            rows = list(rows)
            random.shuffle(rows)
            cut = int(len(rows) * train_fraction)
            return rows[:cut], rows[cut:]
        def summarize(rows):
            values = [float(row['value']) for row in rows]
            return {'count': len(values), 'mean': sum(values) / len(values)}
        """,
        "pipeline/io.py": """
        from pathlib import Path
        def write_report(path, value): Path(path).write_text(str(value))
        """,
        "pipeline/metrics.py": """
        def mean(values): return sum(values) / len(values) if values else 0.0
        def ordered(values): return sorted(values, key=lambda row: (row['group'], row['timestamp']))
        """,
        "data/measurements.csv": """group,timestamp,value
        A,2024-01-02,12
        B,2024-01-01,4
        A,2024-01-01,8
        B,2024-01-02,6
        """,
        "tests/test_acceptance.py": """
        import unittest
        from pipeline.core import load_rows, summarize
        class VisibleAcceptance(unittest.TestCase):
            def test_load_and_summary(self):
                rows = load_rows('data/measurements.csv')
                self.assertEqual(len(rows), 4)
                self.assertEqual(summarize(rows)['count'], 4)
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": """
        # Deterministic data pipeline
        Preserve input rows, use chronological ordering within groups, create a
        deterministic group-disjoint train/evaluation split, and compute means
        without changing numeric meaning. Acceptance requirements are visible.
        """,
    }
    return files, "Repair the synthetic data pipeline. Preserve all rows, order chronologically within each group, produce a deterministic group-disjoint split, and compute exact numeric summaries. Do not use global randomness. The visible tests are part of the contract."


def _p4(v: dict[str, int]) -> tuple[dict[str, str], str]:
    files = {
        "compatpkg/__init__.py": "from .api import Client, Service, make_client\nfrom .codec import encode, decode\n",
        "compatpkg/api.py": """
        class Service:
            def __init__(self, name, timeout=30): self.name, self.timeout = name, timeout
            def request(self, path, timeout=None): return {'name': self.name, 'path': path, 'timeout': self.timeout}
        class Client(Service): pass
        def make_client(name, timeout=30): return Client(name, timeout)
        """,
        "compatpkg/codec.py": """
        import json
        def encode(client): return json.dumps({'name': client.name, 'timeout': client.timeout}, sort_keys=True)
        def decode(value):
            data = json.loads(value)
            data.setdefault('timeout', 30)
            return data
        """,
        "compatpkg/legacy.py": """
        from .api import Client, make_client
        def old_client(name, timeout=30): return make_client(name, timeout)
        """,
        "compatpkg/new_api.py": """
        from .api import Service
        def service(name, timeout=30): return Service(name, timeout)
        """,
        "tests/test_acceptance.py": """
        import unittest
        from compatpkg import Client, make_client
        class VisibleAcceptance(unittest.TestCase):
            def test_legacy_constructor(self): self.assertIsInstance(make_client('visible'), Client)
            def test_default_timeout(self): self.assertEqual(make_client('visible').request('/x')['timeout'], 30)
        if __name__ == '__main__': unittest.main()
        """,
        "README.md": """
        # Compatibility refactor
        Add the Service API while preserving Client, make_client, old_client,
        encode, and decode. Per-request timeout overrides must work, defaults
        remain 30, and encoded legacy objects remain stable. Tests are visible.
        """,
    }
    return files, "Refactor the client into the documented Service API without breaking Client, make_client, old_client, encode, or decode. Honor per-request timeout overrides while preserving the default of 30 and stable encoded data. Use the visible tests as the objective contract."


def make_instance(family: str, seed: int) -> TaskInstance:
    if family not in FAMILIES:
        raise ValueError(f"unknown public characterization family: {family}")
    builders = {"P1_multi_file_debug": _p1, "P2_config_state": _p2, "P3_data_pipeline": _p3, "P4_compat_refactor": _p4}
    variant = _variant(seed)
    files, prompt = builders[family](variant)
    return TaskInstance(family, seed, prompt, files, variant)


def materialize(instance: TaskInstance, workspace: Path) -> Path:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=False)
    _write(workspace, instance.files)
    return workspace


def workspace_digest(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in workspace.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(workspace).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def visible_evaluator_digest(instance: TaskInstance) -> str:
    return hashlib.sha256(instance.files["tests/test_acceptance.py"].encode()).hexdigest()


def manifest(instances: list[TaskInstance]) -> dict[str, object]:
    return {
        "suite": SUITE_NAME,
        "version": SUITE_VERSION,
        "evaluation_class": "public_characterization",
        "instances": [{"family": i.family, "seed": i.seed, "task_id": i.task_id, "workspace_hash": workspace_digest_from_files(i.files), "prompt_hash": hashlib.sha256(i.prompt.encode()).hexdigest(), "visible_evaluator_hash": visible_evaluator_digest(i)} for i in instances],
    }


def workspace_digest_from_files(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode()); digest.update(b"\0"); digest.update(textwrap.dedent(files[name]).lstrip().encode())
    return digest.hexdigest()
