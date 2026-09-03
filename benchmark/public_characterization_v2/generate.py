"""Deterministic V2 task generation with public contracts and edit scopes."""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import FAMILIES, IGNORED_GENERATED_DIRS, IGNORED_GENERATED_SUFFIXES, SUITE_NAME, SUITE_VERSION


@dataclass(frozen=True)
class TaskInstance:
    family: str
    seed: int
    prompt: str
    files: dict[str, str]
    specification: dict[str, Any]
    edit_scope: dict[str, list[str]]
    verifier: str

    @property
    def task_id(self) -> str:
        return f"{SUITE_NAME}:{self.family}@{self.seed}"

    @property
    def task_spec_hash(self) -> str:
        return sha256_json(self.specification)

    @property
    def edit_scope_hash(self) -> str:
        return sha256_json(self.edit_scope)

    @property
    def visible_verifier_hash(self) -> str:
        return hashlib.sha256(self.verifier.encode()).hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def _variant(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    return {"a": rng.randint(7, 13), "b": rng.randint(2, 5), "threshold": rng.randint(4, 9)}


def _common_files(readme: str, tests: str, data: dict[str, str]) -> dict[str, str]:
    return {"README.md": readme, "tests/test_contract.py": tests, **data}


def _verifier_script(family: str) -> str:
    return f'''#!/usr/bin/env python3
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verifier.contract import checks

print(json.dumps({{"family": {family!r}, "checks": checks(Path(__file__).resolve().parents[1])}}, sort_keys=True))
'''


def _make(family: str, seed: int, prompt: str, requirements: list[str], files: dict[str, str], verifier_checks: list[str]) -> TaskInstance:
    edit_scope = {
        "editable": [
            p for p in ("app/**/*.py", "settings/**/*.py", "pipeline/**/*.py", "compatpkg/**/*.py", "data/*.json", "data/*.csv")
            if any(name.startswith(p.split("/")[0] + "/") for name in files)
        ],
        "immutable": ["README.md", "tests/**", "verifier/**", ".ekalavya/**"],
        "generated_ignored": [".pytest_cache/**", "__pycache__/**", "*.pyc"],
    }
    specification = {
        "suite": SUITE_NAME, "version": SUITE_VERSION, "family": family, "seed": seed,
        "requirements": requirements, "checks": verifier_checks,
        "evaluation_contract": "controller-owned evaluator and visible verifier must agree on an unchanged workspace",
    }
    files = dict(files)
    files["verifier/contract.py"] = _contract_source(family)
    files["verifier/verify.py"] = _verifier_script(family)
    files[".ekalavya/edit-scope.json"] = json.dumps(edit_scope, indent=2, sort_keys=True)
    files[".ekalavya/task.json"] = json.dumps({"family": family, "seed": seed}, sort_keys=True)
    return TaskInstance(family, seed, prompt, files, specification, edit_scope, files["verifier/verify.py"])


def _p1(seed: int) -> TaskInstance:
    v = _variant(seed)
    return _make(
        "P1_multi_file_debug", seed,
        "Repair the inventory service while preserving imports. Run `python verifier/verify.py`; all eight named checks define the behavioral contract.",
        ["versioned derived totals invalidate after mutation", "cache repeated totals", "normalize names", "return ascending IDs", "preserve fractional numeric summaries", "make the cross-module report expose the repaired behavior"],
        _common_files(
            """# Inventory service V2\nRepair the interacting cache, catalogue, numeric-summary, and cross-module report behavior.\nThe public verifier names all eight requirements and is readable. Do not edit tests, verifier, or `.ekalavya`.\n""",
            """import unittest\nfrom app.store import Store\nclass PublicContractSmoke(unittest.TestCase):\n    def test_imports(self): self.assertIsNotNone(Store)\n""",
            {
                "app/__init__.py": "from .store import Store, DerivedTotals\nfrom .catalog import find, sorted_ids, summarize\nfrom .service import report\n",
                "app/store.py": """class Store:\n    def __init__(self, values=None): self.values, self.version = dict(values or {}), 0\n    def put(self, key, value): self.values[key] = value; self.version += 1\n    def get(self, key): return self.values[key]\n\nclass DerivedTotals:\n    def __init__(self, store): self.store, self.cache, self.parse_calls = store, {}, 0\n    def total(self, key):\n        if key in self.cache: return self.cache[key]\n        self.parse_calls += 1\n        value = sum(float(part.strip()) for part in self.store.get(key).split(','))\n        self.cache[key] = value\n        return value\n""",
                "app/catalog.py": """def find(items, name): return [item for item in items if item['name'] == name]\ndef sorted_ids(items): return [item['id'] for item in items]\ndef summarize(items): return {'count': len(items), 'total': sum(int(item['amount']) for item in items)}\n""",
                "app/io.py": """import json\nfrom pathlib import Path\ndef read_items(path): return json.loads(Path(path).read_text())\n""",
                "app/service.py": """from .catalog import find, sorted_ids, summarize\nfrom .io import read_items\ndef report(path, name): return {'matches': find(read_items(path), name), 'ids': sorted_ids(read_items(path)), 'summary': summarize(read_items(path))}\n""",
                "data/items.json": json.dumps([{"id": 30, "name": "Alpha", "amount": v["a"] + 0.5}, {"id": 10, "name": " beta ", "amount": v["b"] + 0.25}, {"id": 20, "name": "ALPHA", "amount": 4.25}], indent=2),
            },
        ),
        ["initial total", "cache reuse", "version invalidation", "versioned parse count", "normalized lookup", "ascending identifiers", "fractional summary", "cross-module report"],
    )


def _p2(seed: int) -> TaskInstance:
    return _make(
        "P2_config_state", seed,
        "Repair settings and session state. Run `python verifier/verify.py`; precedence, typed values, isolation, invalidation, active state, and round-trip behavior are independently scored.",
        ["defaults < file < environment < CLI", "typed values survive every source", "user state is isolated", "stale state is invalidated", "active session follows the loaded user", "state serializes and round-trips", "reset clears active state"],
        _common_files(
            """# Settings and session state V2\nImplement the documented precedence and typed configuration contract. Session state must isolate users, invalidate stale values, preserve active-session semantics, and round-trip through serialization.\n""",
            """import unittest\nfrom settings.loader import load_settings\nclass PublicContractSmoke(unittest.TestCase):\n    def test_imports(self): self.assertEqual(load_settings()['mode'], 'safe')\n""",
            {
                "settings/__init__.py": "from .loader import load_settings\nfrom .state import Session\n",
                "settings/loader.py": """import json\nDEFAULTS = {'mode': 'safe', 'limit': 10, 'enabled': False}\ndef load_settings(path=None, environ=None, argv=None):\n    result = dict(DEFAULTS)\n    if path:\n        with open(path, encoding='utf-8') as handle: result.update(json.load(handle))\n    for key, value in (environ or {}).items():\n        if key.startswith('APP_'): result[key[4:].lower()] = value\n    for item in argv or []:\n        if item.startswith('--') and '=' in item: result[item[2:].split('=', 1)[0]] = item.split('=', 1)[1]\n    return result\n""",
                "settings/state.py": """import json\nclass Session:\n    def __init__(self): self.current, self._cache = None, {}\n    def load(self, user):\n        if self.current is not None: return self.current\n        self.current = self._cache.setdefault(user, {'user': user, 'limit': 10, 'stale': False})\n        return self.current\n    def invalidate(self, user): self._cache.pop(user, None)\n    def serialize(self): return json.dumps(self._cache, sort_keys=True)\n    def restore(self, payload): self._cache = json.loads(payload)\n    def reset(self): self.current = None\n""",
                "settings/cli.py": "from .loader import load_settings\ndef effective(path=None, env=None, argv=None): return load_settings(path, env, argv)\n",
            },
        ),
        ["default", "precedence", "typed values", "user isolation", "stale invalidation", "active session", "serialization round trip", "reset"],
    )


def _p3(seed: int) -> TaskInstance:
    return _make(
        "P3_data_pipeline", seed,
        "Repair the scientific data pipeline. Run `python verifier/verify.py`; chronology, group disjointness, determinism, leakage, numeric preservation, and report semantics are independently scored.",
        ["retain every row", "order chronologically within groups", "split by disjoint groups", "make the split deterministic", "avoid global shuffling", "preserve numeric meaning", "emit correct summary", "preserve report schema"],
        _common_files(
            """# Scientific data pipeline V2\nPreserve scientific ordering and group semantics. The visible verifier is the local behavioral contract; do not edit `tests/`, `verifier/`, or `.ekalavya/`.\n""",
            """import unittest\nfrom pipeline.core import load_rows\nclass PublicContractSmoke(unittest.TestCase):\n    def test_imports(self): self.assertEqual(len(load_rows('data/measurements.csv')), 6)\n""",
            {
                "pipeline/__init__.py": "from .core import load_rows, split_by_group, summarize\nfrom .metrics import ordered\n",
                "pipeline/core.py": """import csv, random\nfrom pathlib import Path\ndef load_rows(path):\n    with Path(path).open(newline='') as handle: return list(csv.DictReader(handle))\ndef split_by_group(rows, train_fraction=0.5):\n    rows = list(rows); random.shuffle(rows); cut = int(len(rows) * train_fraction); return rows[:cut], rows[cut:]\ndef summarize(rows):\n    values = [float(row['value']) for row in rows]; return {'count': len(values), 'mean': sum(values) / len(values)}\n""",
                "pipeline/metrics.py": """def ordered(values): return list(values)\ndef report(rows): return {'rows': list(reversed(rows))}\n""",
                "data/measurements.csv": "group,timestamp,value\nA,2024-01-03,12\nB,2024-01-01,4\nA,2024-01-01,8\nB,2024-01-03,6\nA,2024-01-02,10\nB,2024-01-02,2\n",
            },
        ),
        ["all rows retained", "chronological ordering", "group-disjoint split", "deterministic split", "no global shuffle", "numeric preservation", "summary", "report schema"],
    )


def _p4(seed: int) -> TaskInstance:
    v = _variant(seed)
    return _make(
        "P4_compat_refactor", seed,
        "Refactor the compatibility package without breaking legacy APIs. Run `python verifier/verify.py`; all eight compatibility behaviors are independently scored.",
        ["Service API exists", "legacy Client remains a Service", "per-request timeout overrides work", "default timeout remains 30", "factory propagates timeout", "codec round-trips all fields", "codec supplies the legacy default", "new API request path works"],
        _common_files(
            """# Compatibility refactor V2\nAdd the Service API while preserving Client, make_client, old_client, encode, and decode. The visible verifier defines the compatibility contract.\n""",
            """import unittest\nfrom compatpkg import Service\nclass PublicContractSmoke(unittest.TestCase):\n    def test_service_exists(self): self.assertTrue(Service)\n""",
            {
                "compatpkg/__init__.py": "from .api import Client, Service, make_client\nfrom .codec import encode, decode\n",
                "compatpkg/api.py": """class Service:\n    def __init__(self, name, timeout=30): self.name, self.timeout = name, timeout\n    def request(self, path, timeout=None): return {'name': self.name, 'path': path, 'timeout': self.timeout}\nclass Client:\n    def __init__(self, name): self.name = name\ndef make_client(name, timeout=30): return Client(name)\n""",
                "compatpkg/codec.py": """import json\ndef encode(client): return json.dumps({'name': client.name})\ndef decode(value):\n    data = json.loads(value); data.setdefault('timeout', 30); return data\n""",
                "compatpkg/legacy.py": "from .api import Client, make_client\ndef old_client(name, timeout=30): return make_client(name, timeout)\n",
                "compatpkg/new_api.py": """from .api import Service\ndef service(name, timeout=30): return Service(name)\n""",
            },
        ),
        ["service type", "legacy compatibility", "per-request timeout", "default timeout", "factory propagation", "codec round trip", "codec default", "new API request"],
    )


def make_instance(family: str, seed: int) -> TaskInstance:
    if family not in FAMILIES:
        raise ValueError(f"unknown public characterization family: {family}")
    return {"P1_multi_file_debug": _p1, "P2_config_state": _p2, "P3_data_pipeline": _p3, "P4_compat_refactor": _p4}[family](seed)


def materialize(instance: TaskInstance, workspace: Path) -> Path:
    if workspace.exists(): shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    _write(workspace, instance.files)
    return workspace


def workspace_digest(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in workspace.rglob("*") if p.is_file() and p.suffix not in IGNORED_GENERATED_SUFFIXES and not any(part in IGNORED_GENERATED_DIRS for part in p.parts)):
        digest.update(path.relative_to(workspace).as_posix().encode()); digest.update(b"\0"); digest.update(path.read_bytes())
    return digest.hexdigest()


def _contract_source(family: str) -> str:
    return _CONTRACTS[family]


_CONTRACTS = {
    "P1_multi_file_debug": """import json\nfrom pathlib import Path\ndef checks(root):\n from app.store import Store, DerivedTotals\n from app.catalog import find, sorted_ids, summarize\n from app.service import report\n items=json.loads((root/'data/items.json').read_text()); a=float(items[0]['amount']); b=float(items[1]['amount']); expected=a+b\n store=Store({'numbers': f'{a},{b}'}); totals=DerivedTotals(store); first=totals.total('numbers'); cached=totals.total('numbers'); store.put('numbers', f'{a+1},{b}')\n return [first==expected, cached==expected and totals.parse_calls==1, totals.total('numbers')==expected+1, totals.parse_calls==2, len(find(items,' alpha '))==2, sorted_ids(items)==[10,20,30], summarize(items)['total']==sum(float(i['amount']) for i in items), report(root/'data/items.json','alpha')['summary']['total']==sum(float(i['amount']) for i in items)]\n""",
    "P2_config_state": """import json, tempfile\nfrom pathlib import Path\ndef checks(root):\n from settings.loader import load_settings\n from settings.state import Session\n cfg=Path(tempfile.mkstemp(suffix='.json')[1]); cfg.write_text(json.dumps({'mode':'file','limit':4,'enabled':False}))\n try:\n  defaults=load_settings(); precedence=load_settings(cfg, {'APP_LIMIT':'7','APP_ENABLED':'true'}, ['--limit=9']); typed=precedence['limit']==9 and precedence['enabled'] is True\n finally: cfg.unlink(missing_ok=True)\n s=Session(); first=s.load('ada'); second=s.load('lin'); active=s.current.get('user') if s.current else None; s.invalidate('ada'); payload=s.serialize(); restored=Session(); restored.restore(payload)\n try: stale=s.load('ada') is not first\n except Exception: stale=False\n return [defaults['mode']=='safe', precedence['limit']==9 and precedence['mode']=='file', typed, first['user']=='ada' and second['user']=='lin', stale, active=='lin', restored.load('lin')==second, (s.reset() is None and s.current is None)]\n""",
    "P3_data_pipeline": """import json, random\nfrom pathlib import Path\ndef checks(root):\n from pipeline.core import load_rows, split_by_group, summarize\n from pipeline.metrics import ordered, report\n rows=load_rows(str(root/'data/measurements.csv')); seed=json.loads((root/'.ekalavya/task.json').read_text())['seed']; random.seed(seed); t1,e1=split_by_group(rows); t2,e2=split_by_group(rows); groups={r['group'] for r in t1},{r['group'] for r in e1}; expected=[('A','2024-01-01'),('A','2024-01-02'),('A','2024-01-03'),('B','2024-01-01'),('B','2024-01-02'),('B','2024-01-03')]; positions={id(row):i for i,row in enumerate(rows)}; preserves=all([positions[id(row)] for row in part]==sorted(positions[id(row)] for row in part) for part in (t1,e1))\n return [len(rows)==6 and len(t1)+len(e1)==6, [(r['group'],r['timestamp']) for r in ordered(rows)]==expected, groups[0].isdisjoint(groups[1]), t1==t2 and e1==e2, preserves, summarize(rows)['mean']==7.0, summarize(rows)['count']==6 and sum(float(r['value']) for r in rows)==42.0, report(rows)['rows']==rows]\n""",
    "P4_compat_refactor": """import json\ndef checks(root):\n from compatpkg import Client, Service, decode, encode, make_client\n from compatpkg.legacy import old_client\n from compatpkg.new_api import service\n client=make_client('visible')\n try: override=client.request('/x', timeout=7)['timeout']==7; default=client.request('/x')['timeout']==30\n except (AttributeError, TypeError, KeyError): override=default=False\n try: factory=make_client('x', 12).timeout==12\n except (AttributeError, TypeError): factory=False\n try: new_request=service('new',8).request('/new')['timeout']==8\n except (AttributeError, TypeError, KeyError): new_request=False\n return [isinstance(service('s'), Service), isinstance(client, Client) and isinstance(old_client('old'), Client) and isinstance(client, Service), override, default, factory, decode(encode(client))=={'name':'visible','timeout':30}, decode('{"name":"legacy"}')['timeout']==30, new_request]\n""",
}
