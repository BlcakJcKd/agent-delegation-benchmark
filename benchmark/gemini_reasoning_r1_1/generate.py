"""Fresh deterministic public task sources for the R1 reasoning screen.

The generated projects contain ordinary maintenance defects and a public
behavioral contract.  They contain no reference repair or controller source.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path

from . import FAMILIES, SEEDS, SUITE_NAME, SUITE_VERSION


@dataclass(frozen=True)
class TaskInstance:
    family: str
    seed: int
    prompt: str
    files: dict[str, str]
    editable: tuple[str, ...]
    immutable: tuple[str, ...]

    @property
    def task_id(self) -> str:
        return f"{SUITE_NAME}:{self.family}@{self.seed}"

    @property
    def variant(self) -> dict[str, object]:
        rng = random.Random(self.seed)
        return {"amount": f"{rng.randint(2, 9)}.{rng.randint(1, 9)}", "limit": rng.randint(2, 5)}


def _dedent(files: dict[str, str]) -> dict[str, str]:
    return {name: textwrap.dedent(content).lstrip() for name, content in files.items()}


def _r1(seed: int) -> tuple[dict[str, str], str, tuple[str, ...], tuple[str, ...]]:
    items = [
        {"sku": "A-10", "name": "  Alpha  ", "category": "tools", "amount": "4.25"},
        {"sku": "A-2", "name": "ALPHA", "category": "tools", "amount": "1.75"},
        {"sku": "B-3", "name": "Beta", "category": "parts", "amount": "3.50"},
        {"sku": "B-12", "name": " beta ", "category": "parts", "amount": "2.25"},
    ]
    files = _dedent({
        "inventory/__init__.py": "from .service import InventoryService\n",
        "inventory/models.py": """
            from dataclasses import dataclass
            from decimal import Decimal

            @dataclass(frozen=True)
            class Item:
                sku: str
                name: str
                category: str
                amount: Decimal

            def make_item(raw):
                return Item(raw['sku'], raw['name'], raw['category'], Decimal(raw['amount']))
        """,
        "inventory/storage.py": """
            from .models import make_item

            class InventoryRepository:
                def __init__(self, rows):
                    self._items = {row['sku']: make_item(row) for row in rows}
                    self._version = 0

                @property
                def version(self):
                    return self._version

                def replace_amount(self, sku, amount):
                    item = self._items[sku]
                    self._items[sku] = type(item)(item.sku, item.name, item.category, amount)

                def all_items(self):
                    return list(self._items.values())
        """,
        "inventory/cache.py": """
            class SummaryCache:
                def __init__(self):
                    self._values = {}
                    self.parse_count = 0

                def get(self, category, version):
                    if category in self._values:
                        return self._values[category]
                    self.parse_count += 1
                    return None

                def put(self, category, version, value):
                    self._values[category] = value
        """,
        "inventory/search.py": """
            def normalize(value):
                return value

            def find(items, query):
                wanted = normalize(query)
                return [item for item in items if normalize(item.name) == wanted]
        """,
        "inventory/ordering.py": """
            def stable_skus(items):
                return [item.sku for item in sorted(items, key=lambda item: item.sku)]
        """,
        "inventory/analytics.py": """
            from decimal import Decimal

            def category_total(items, category):
                return sum(int(item.amount) for item in items if item.category == category)
        """,
        "inventory/service.py": """
            import json
            from pathlib import Path
            from .analytics import category_total
            from .cache import SummaryCache
            from .ordering import stable_skus
            from .search import find
            from .storage import InventoryRepository

            class InventoryService:
                def __init__(self, path):
                    self._rows = json.loads(Path(path).read_text())
                    self.repository = InventoryRepository(self._rows)
                    self.cache = SummaryCache()

                def replace_amount(self, sku, amount):
                    self.repository.replace_amount(sku, amount)

                def summary(self, category):
                    cached = self.cache.get(category, self.repository.version)
                    if cached is not None:
                        return cached
                    items = [item for item in self.repository.all_items() if item.category == category]
                    result = {'category': category, 'total': category_total(items, category), 'count': len(items)}
                    self.cache.put(category, self.repository.version, result)
                    return result

                def search(self, query):
                    return find(self.repository.all_items(), query)

                def report(self, query, category):
                    return {'matches': [item.sku for item in self.search(query)], 'skus': stable_skus(self.repository.all_items()), 'summary': self.summary(category)}
        """,
        "data/items.json": json.dumps(items, indent=2),
        "tests/test_contract.py": """
            import json
            import unittest
            from decimal import Decimal
            from pathlib import Path
            from inventory.service import InventoryService

            class ContractTests(unittest.TestCase):
                def setUp(self):
                    self.service = InventoryService(Path('data/items.json'))

                def test_c1_fractional_amounts(self):
                    self.assertEqual(self.service.repository.all_items()[0].amount, Decimal('4.25'))

                def test_c2_version_changes_on_mutation(self):
                    before = self.service.repository.version
                    self.service.replace_amount('A-10', Decimal('8.50'))
                    self.assertGreater(self.service.repository.version, before)

                def test_c3_repeated_summary_is_cached(self):
                    self.service.summary('tools')
                    before = self.service.cache.parse_count
                    self.service.summary('tools')
                    self.assertEqual(self.service.cache.parse_count, before)

                def test_c4_mutation_invalidates_summary(self):
                    before = self.service.summary('tools')['total']
                    self.service.replace_amount('A-10', Decimal('8.50'))
                    self.assertNotEqual(self.service.summary('tools')['total'], before)

                def test_c5_categories_have_independent_summaries(self):
                    tools = self.service.summary('tools')
                    parts = self.service.summary('parts')
                    self.assertNotEqual(tools['category'], parts['category'])
                    self.assertEqual(self.service.summary('tools'), tools)

                def test_c6_search_normalizes_case_and_space(self):
                    self.assertEqual({item.sku for item in self.service.search(' alpha ')}, {'A-10', 'A-2'})

                def test_c7_decimal_aggregation_is_exact(self):
                    self.assertEqual(self.service.summary('tools')['total'], Decimal('6.00'))

                def test_c8_report_composes_stable_catalogue_and_summary(self):
                    report = self.service.report('BETA', 'parts')
                    self.assertEqual(report['skus'], ['A-2', 'A-10', 'B-3', 'B-12'])
                    self.assertEqual(report['matches'], ['B-3', 'B-12'])
                    self.assertEqual(report['summary']['total'], Decimal('5.75'))

            if __name__ == '__main__': unittest.main()
        """,
        "README.md": """
            # Inventory maintenance

            Maintain the existing inventory service so that monetary amounts,
            versioned mutations, derived summaries, normalized search, stable
            catalogue ordering, and composed reports behave consistently.
            Preserve the public InventoryService API. The acceptance contract
            is fully visible in tests/test_contract.py.
        """,
    })
    return files, "Maintain the inventory service contract. Correct its observable behavior across monetary parsing, mutation versioning, derived-summary caching, normalized search, stable catalogue ordering, exact aggregation, and report composition. Preserve the public API and validate the complete visible contract.", ("inventory/**/*.py",), ("tests/**", "data/**", "README.md")


def _r2(seed: int) -> tuple[dict[str, str], str, tuple[str, ...], tuple[str, ...]]:
    files = _dedent({
        "clientkit/__init__.py": "from .client import Client\nfrom .factory import make_client\nfrom .legacy import old_client\n",
        "clientkit/types.py": """
            from dataclasses import dataclass

            @dataclass(frozen=True)
            class Request:
                path: str
                timeout: int
                idempotent: bool = True

            @dataclass(frozen=True)
            class Response:
                path: str
                attempts: int
                timeout: int
        """,
        "clientkit/transport.py": """
            from .types import Response

            class Transport:
                def send(self, request, attempts=1):
                    return Response(request.path, attempts, request.timeout)
        """,
        "clientkit/retry.py": """
            def attempts_for(request, retries):
                return retries + 1
        """,
        "clientkit/codec.py": """
            import json

            def encode(client):
                return json.dumps({'base_url': client.base_url, 'timeout': client.timeout})

            def decode(value):
                data = json.loads(value)
                return {'base_url': data['base_url'], 'timeout': data.get('timeout', 30)}
        """,
        "clientkit/client.py": """
            from .retry import attempts_for
            from .transport import Transport
            from .types import Request

            class Client:
                def __init__(self, base_url, timeout=30, retries=2, transport=None):
                    self.base_url, self.timeout, self.retries = base_url, timeout, retries
                    self.transport = transport or Transport()

                def request(self, path, timeout=None, idempotent=True):
                    request = Request(path, self.timeout, idempotent)
                    return self.transport.send(request, attempts_for(request, self.retries))

                def request_many(self, paths):
                    return [self.request(path) for path in paths]
        """,
        "clientkit/factory.py": """
            from .client import Client

            def make_client(base_url, **options):
                return Client(base_url)
        """,
        "clientkit/legacy.py": """
            from .client import Client

            def old_client(base_url, timeout=30, retries=2):
                return Client(base_url, timeout=timeout, retries=retries)
        """,
        "clientkit/report.py": """
            def summarize(responses):
                return {'paths': [response.path for response in responses], 'attempts': sum(response.attempts for response in responses)}
        """,
        "tests/test_contract.py": """
            import unittest
            from clientkit.client import Client
            from clientkit.codec import decode, encode
            from clientkit.factory import make_client
            from clientkit.legacy import old_client
            from clientkit.report import summarize
            from clientkit.types import Response

            class ContractTests(unittest.TestCase):
                def test_c1_legacy_shape_and_defaults(self):
                    client = old_client('https://example.test')
                    self.assertIsInstance(client, Client)
                    self.assertEqual((client.timeout, client.retries), (30, 2))

                def test_c2_request_timeout_override(self):
                    self.assertEqual(Client('x').request('/a', timeout=7).timeout, 7)

                def test_c3_non_idempotent_requests_do_not_retry(self):
                    response = Client('x', retries=3).request('/write', idempotent=False)
                    self.assertEqual(response.attempts, 1)

                def test_c4_factory_propagates_options(self):
                    client = make_client('x', timeout=11, retries=4)
                    self.assertEqual((client.timeout, client.retries), (11, 4))

                def test_c5_existing_constructor_patterns_remain_compatible(self):
                    client = Client('x', 9, 1)
                    self.assertEqual(client.request('/a').timeout, 9)
                    self.assertEqual(old_client('x', 8, 0).timeout, 8)

                def test_c6_codec_round_trip_preserves_policy(self):
                    client = Client('x', timeout=13, retries=5)
                    restored = decode(encode(client))
                    self.assertEqual(restored, {'base_url': 'x', 'timeout': 13, 'retries': 5})

                def test_c7_batch_preserves_input_order(self):
                    self.assertEqual([r.path for r in Client('x').request_many(['/b', '/a'])], ['/b', '/a'])

                def test_c8_report_composes_response_metadata(self):
                    report = summarize([Response('/a', 1, 3), Response('/b', 2, 4)])
                    self.assertEqual(report, {'paths': ['/a', '/b'], 'attempts': 3})

            if __name__ == '__main__': unittest.main()
        """,
        "README.md": """
            # Client compatibility maintenance

            Preserve the established client API while making request policy,
            retries, factories, legacy construction, serialization, batching,
            and reporting behave consistently. The complete behavioral
            contract is visible in tests/test_contract.py.
        """,
    })
    return files, "Maintain the client compatibility contract. Request-level policy, idempotency-aware retries, factory options, legacy construction, serialization, batching, and reporting must compose without breaking existing callers. The visible contract is authoritative.", ("clientkit/**/*.py",), ("tests/**", "README.md")


def _r3(seed: int) -> tuple[dict[str, str], str, tuple[str, ...], tuple[str, ...]]:
    rows = """group,timestamp,value,quality
        north,2024-02-10T09:00:00,1.25,ok
        south,2024-01-02T10:00:00,2.50,ok
        north,2024-01-02T09:00:00,3.75,ok
        east,2024-03-01T08:00:00,4.25,ok
        south,2024-02-11T10:00:00,5.50, OK 
        east,2024-01-15T08:00:00,6.75,ok
        north,2024-03-04T09:00:00,7.25,ok
        south,2024-03-12T10:00:00,8.50,ok
        east,2024-02-20T08:00:00,9.25,ok
        """
    files = _dedent({
        "experiment/__init__.py": "from .pipeline import run\n",
        "experiment/schema.py": """
            from dataclasses import dataclass
            from datetime import datetime

            @dataclass(frozen=True)
            class Measurement:
                group: str
                timestamp: datetime
                value: float
                quality: str

            def parse_row(row):
                return Measurement(row['group'].strip(), datetime.fromisoformat(row['timestamp']), float(row['value']), row['quality'].strip())
        """,
        "experiment/loader.py": """
            import csv
            from pathlib import Path
            from .schema import parse_row

            def load(path):
                with Path(path).open(newline='') as handle:
                    return [parse_row(row) for row in csv.DictReader(handle)]
        """,
        "experiment/normalize.py": """
            def normalize(rows):
                return list(rows)
        """,
        "experiment/order.py": """
            def chronological(rows):
                return sorted(rows, key=lambda row: row.timestamp.isoformat())
        """,
        "experiment/grouping.py": """
            def groups(rows):
                result = {}
                for row in rows:
                    result.setdefault(row.group, []).append(row)
                return result
        """,
        "experiment/split.py": """
            import random

            def split(rows, fraction=0.67, seed=0):
                values = list(rows)
                random.Random(seed).shuffle(values)
                cut = max(1, int(len(values) * fraction))
                return values[:cut], values[cut:]
        """,
        "experiment/metrics.py": """
            def summary(rows):
                values = [int(row.value) for row in rows]
                return {'count': len(values), 'mean': sum(values) / len(values) if values else 0.0, 'total': sum(values)}
        """,
        "experiment/report.py": """
            def build(train, evaluation):
                return {'schema': 'experiment-v1', 'train_groups': sorted({row.group for row in train}), 'evaluation_groups': sorted({row.group for row in evaluation}), 'train': len(train), 'evaluation': len(evaluation)}
        """,
        "experiment/pipeline.py": """
            from .loader import load
            from .metrics import summary
            from .normalize import normalize
            from .order import chronological
            from .report import build
            from .split import split

            def run(path, seed=0):
                rows = normalize(load(path))
                ordered = chronological(rows)
                train, evaluation = split(ordered, seed=seed)
                return {'rows': ordered, 'train': train, 'evaluation': evaluation, 'metrics': summary(rows), 'report': build(train, evaluation)}
        """,
        "data/measurements.csv": rows,
        "tests/test_contract.py": """
            import unittest
            from pathlib import Path
            from experiment.pipeline import run

            class ContractTests(unittest.TestCase):
                def setUp(self):
                    self.result = run(Path('data/measurements.csv'), seed=1)
                    self.rows = self.result['rows']

                def test_c1_schema_and_row_retention(self):
                    self.assertEqual(len(self.rows), 9)
                    self.assertEqual({row.group for row in self.rows}, {'north', 'south', 'east'})

                def test_c2_numeric_values_preserve_fraction(self):
                    self.assertAlmostEqual(self.result['metrics']['total'], 49.0)
                    self.assertAlmostEqual(self.result['metrics']['mean'], 49.0 / 9.0)

                def test_c3_within_group_chronology(self):
                    for group in {'north', 'south', 'east'}:
                        values = [row.timestamp for row in self.rows if row.group == group]
                        self.assertEqual(values, sorted(values))

                def test_c4_split_is_group_disjoint(self):
                    train = {row.group for row in self.result['train']}
                    evaluation = {row.group for row in self.result['evaluation']}
                    self.assertTrue(train.isdisjoint(evaluation))

                def test_c5_split_retains_each_row_once(self):
                    combined = self.result['train'] + self.result['evaluation']
                    self.assertEqual(sorted(combined, key=lambda row: (row.group, row.timestamp)), self.rows)

                def test_c6_split_is_deterministic(self):
                    again = run(Path('data/measurements.csv'), seed=1)
                    self.assertEqual(self.result['train'], again['train'])
                    self.assertEqual(self.result['evaluation'], again['evaluation'])

                def test_c7_input_order_and_quality_are_stable(self):
                    self.assertEqual(self.rows[0].group, 'east')
                    self.assertEqual({row.quality for row in self.rows}, {'ok'})

                def test_c8_report_schema_and_partition_counts(self):
                    report = self.result['report']
                    self.assertEqual(report['schema'], 'experiment-v1')
                    self.assertEqual(report['train'] + report['evaluation'], 9)
                    self.assertEqual(set(report['train_groups']) | set(report['evaluation_groups']), {'east', 'north', 'south'})

            if __name__ == '__main__': unittest.main()
        """,
        "README.md": """
            # Scientific experiment pipeline

            Preserve scientific meaning while maintaining the pipeline's public
            output: parse typed measurements, retain rows, order chronologically
            within groups, split groups without leakage deterministically, and
            produce stable metrics and report metadata. The visible contract is
            in tests/test_contract.py.
        """,
    })
    return files, "Maintain the scientific pipeline contract. Preserve typed numeric measurements, row identity, chronological within-group behavior, deterministic group-disjoint partitioning, stable input semantics, metrics, and report schema. Do not change the scientific meaning of the data.", ("experiment/**/*.py",), ("tests/**", "data/**", "README.md")


def _r4(seed: int) -> tuple[dict[str, str], str, tuple[str, ...], tuple[str, ...]]:
    files = _dedent({
        "settings/__init__.py": "from .service import SettingsService\n",
        "settings/types.py": """
            from dataclasses import dataclass

            @dataclass(frozen=True)
            class Settings:
                enabled: bool = False
                limit: int = 10
                mode: str = 'safe'
        """,
        "settings/defaults.py": """
            from .types import Settings

            def defaults():
                return Settings()
        """,
        "settings/sources.py": """
            import json
            import os
            from .types import Settings

            def merge(path=None, environ=None, argv=None):
                values = {'enabled': False, 'limit': 10, 'mode': 'safe'}
                if path:
                    with open(path, encoding='utf-8') as handle:
                        values.update(json.load(handle))
                env = environ or os.environ
                for name, key in {'APP_ENABLED': 'enabled', 'APP_LIMIT': 'limit', 'APP_MODE': 'mode'}.items():
                    if env.get(name):
                        values[key] = env[name]
                for argument in argv or []:
                    if '=' in argument:
                        key, value = argument.lstrip('-').split('=', 1)
                        values[key] = value
                return Settings(**values)
        """,
        "settings/session.py": """
            class SessionStore:
                def __init__(self):
                    self._users = {}
                    self.active_user = None

                def activate(self, user):
                    self.active_user = user
                    return self._users.setdefault(user, {'visits': 0})

                def touch(self):
                    self._users[self.active_user]['visits'] += 1

                def reset(self):
                    self.active_user = self.active_user

                def export(self):
                    return {'active_user': self.active_user, 'users': dict(self._users)}

                def restore(self, value):
                    self._users = dict(value['users'])
                    self.active_user = value['active_user']
        """,
        "settings/codec.py": """
            import json

            def encode(store):
                return json.dumps(store.export(), sort_keys=True)

            def decode(value):
                return json.loads(value)
        """,
        "settings/policy.py": """
            def effective(settings):
                if settings.limit < 0:
                    raise ValueError('limit must be non-negative')
                return {'enabled': settings.enabled, 'limit': settings.limit, 'mode': settings.mode}
        """,
        "settings/service.py": """
            from .codec import decode, encode
            from .policy import effective
            from .session import SessionStore
            from .sources import merge

            class SettingsService:
                def __init__(self):
                    self.sessions = SessionStore()

                def load(self, path=None, environ=None, argv=None):
                    return effective(merge(path, environ, argv))

                def save_sessions(self):
                    return encode(self.sessions)

                def restore_sessions(self, value):
                    self.sessions.restore(decode(value))
        """,
        "settings/report.py": """
            def describe(settings, sessions):
                return {'settings': settings, 'active_user': sessions.active_user, 'users': sorted(sessions.export()['users'])}
        """,
        "tests/test_contract.py": """
            import json
            import tempfile
            import unittest
            from pathlib import Path
            from settings.service import SettingsService

            class ContractTests(unittest.TestCase):
                def setUp(self):
                    self.service = SettingsService()

                def test_c1_precedence_across_sources(self):
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as handle:
                        json.dump({'limit': 2, 'mode': 'file'}, handle); handle.flush()
                        result = self.service.load(handle.name, {'APP_LIMIT': '4'}, ['--limit=6'])
                    self.assertEqual(result, {'enabled': False, 'limit': 6, 'mode': 'file'})

                def test_c2_false_and_zero_values_are_preserved(self):
                    result = self.service.load(environ={'APP_ENABLED': 'false', 'APP_LIMIT': '0'})
                    self.assertEqual(result, {'enabled': False, 'limit': 0, 'mode': 'safe'})

                def test_c3_values_are_typed(self):
                    result = self.service.load(environ={'APP_ENABLED': 'true', 'APP_LIMIT': '3'})
                    self.assertIs(result['enabled'], True)
                    self.assertIs(result['limit'], 3)

                def test_c4_users_are_isolated(self):
                    ada = self.service.sessions.activate('ada'); self.service.sessions.touch()
                    lin = self.service.sessions.activate('lin')
                    self.assertEqual(ada['visits'], 1)
                    self.assertEqual(lin['visits'], 0)

                def test_c5_active_user_and_reset(self):
                    self.service.sessions.activate('ada')
                    self.service.sessions.reset()
                    self.assertIsNone(self.service.sessions.active_user)

                def test_c6_serialization_restores_all_state(self):
                    self.service.sessions.activate('ada'); self.service.sessions.touch()
                    self.service.sessions.activate('lin')
                    encoded = self.service.save_sessions()
                    restored = SettingsService(); restored.restore_sessions(encoded)
                    self.assertEqual(restored.sessions.export(), self.service.sessions.export())

                def test_c7_restored_state_can_switch_and_reset(self):
                    self.service.sessions.activate('ada')
                    other = SettingsService(); other.restore_sessions(self.service.save_sessions())
                    other.sessions.activate('lin'); other.sessions.reset()
                    self.assertIsNone(other.sessions.active_user)
                    self.assertIn('ada', other.sessions.export()['users'])

                def test_c8_report_preserves_policy_and_session_summary(self):
                    self.service.sessions.activate('ada')
                    result = self.service.load(environ={'APP_LIMIT': '0'})
                    from settings.report import describe
                    self.assertEqual(describe(result, self.service.sessions), {'settings': result, 'active_user': 'ada', 'users': ['ada']})

            if __name__ == '__main__': unittest.main()
        """,
        "README.md": """
            # Configuration and session maintenance

            Preserve the settings service contract across source precedence,
            typed false/zero values, independent user sessions, reset, state
            serialization, restoration, policy validation, and reporting. All
            observable requirements are shown in tests/test_contract.py.
        """,
    })
    return files, "Maintain the configuration and session contract. Defaults, file, environment, and CLI sources must compose with typed false/zero values; independent users, active state, reset, serialization/restoration, policy, and reporting must remain correct.", ("settings/**/*.py",), ("tests/**", "README.md")


def make_instance(family: str, seed: int | None = None) -> TaskInstance:
    if family not in FAMILIES:
        raise ValueError(f"unknown R1 family: {family}")
    actual_seed = SEEDS[family] if seed is None else seed
    builders = {"R1_maintenance": _r1, "R2_api_compat": _r2, "R3_scientific_pipeline": _r3, "R4_config_state": _r4}
    files, prompt, editable, immutable = builders[family](actual_seed)
    files, prompt = _fresh_variant(family, files, prompt)
    return TaskInstance(family, actual_seed, prompt, files, editable, immutable)


def _fresh_variant(family: str, files: dict[str, str], prompt: str) -> tuple[dict[str, str], str]:
    """Create R1.1 variants without changing their observable contracts."""
    files = dict(files)
    if family == "R1_maintenance":
        replacements = (
            ("A-10", "C-21"), ("A-2", "C-4"), ("B-3", "D-5"), ("B-12", "D-16"),
            ("ALPHA", "GAMMA"), ("Alpha", "Gamma"), ("BETA", "DELTA"),
            ("Beta", "Delta"), ("beta", "delta"), ("tools", "hardware"),
            ("parts", "supplies"), ("4.25", "6.40"), ("1.75", "2.60"),
            ("3.50", "5.30"), ("2.25", "4.70"), ("8.50", "10.20"),
            ("6.00", "9.00"), ("5.75", "10.00"),
        )
        files = {name: _replace_all(content, replacements) for name, content in files.items()}
        files["tests/test_contract.py"] = files["tests/test_contract.py"].replace("' alpha '", "' gamma '")
    elif family == "R2_api_compat":
        test = files["tests/test_contract.py"]
        test = test.replace("'/a'", "'/c'").replace("'/b'", "'/d'")
        test = test.replace("'https://example.test'", "'https://example.test'")
        test = test.replace("timeout=7", "timeout=17")
        test = test.replace("timeout=17).timeout, 7", "timeout=17).timeout, 17")
        test = test.replace("'base_url': 'x'", "'base_url': 'service.example'")
        test = test.replace("Client('x')", "Client('service.example')")
        test = test.replace("Client('x',", "Client('service.example',")
        test = test.replace("old_client('x',", "old_client('service.example',")
        test = test.replace("make_client('x',", "make_client('service.example',")
        files["tests/test_contract.py"] = test
    elif family == "R3_scientific_pipeline":
        replacements = (
            ("north", "amber"), ("south", "cobalt"), ("east", "indigo"),
            ("1.25", "1.125"), ("2.50", "2.875"), ("3.75", "3.625"),
            ("4.25", "4.875"), ("5.50", "5.125"), ("6.75", "6.625"),
            ("7.25", "7.875"), ("8.50", "8.125"), ("9.25", "9.75"),
            ("49.0", "50.0"), ("49.0 / 9.0", "50.0 / 9.0"),
        )
        files = {name: _replace_all(content, replacements) for name, content in files.items()}
        files["tests/test_contract.py"] = files["tests/test_contract.py"].replace("self.rows[0].group, 'indigo'", "self.rows[0].group, 'amber'")
    elif family == "R4_config_state":
        files["tests/test_contract.py"] = _replace_all(files["tests/test_contract.py"], (("'ada'", "'eve'"), ("'lin'", "'zoe'")))
    return files, prompt + "\nThis is a fresh matched R1.1 task variant; preserve the same observable contract."


def _replace_all(value: str, replacements: tuple[tuple[str, str], ...]) -> str:
    for old, new in replacements:
        value = value.replace(old, new)
    return value


def materialize(instance: TaskInstance, workspace: Path) -> Path:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for name, content in instance.files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return workspace


def digest_files(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode()); digest.update(b"\0"); digest.update(files[name].encode())
    return digest.hexdigest()


def workspace_digest(workspace: Path) -> str:
    files = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and not any(part in {"__pycache__", ".pytest_cache"} for part in path.parts) and path.suffix != ".pyc":
            files[path.relative_to(workspace).as_posix()] = path.read_text(encoding="utf-8")
    return digest_files(files)


def task_hashes(instance: TaskInstance) -> dict[str, str]:
    return {
        "task_spec_hash": hashlib.sha256(instance.prompt.encode()).hexdigest(),
        "visible_verifier_hash": hashlib.sha256(instance.files["tests/test_contract.py"].encode()).hexdigest(),
        "generated_workspace_hash": digest_files(instance.files),
        "allowed_edit_manifest_hash": hashlib.sha256(json.dumps({"editable": instance.editable, "immutable": instance.immutable}, sort_keys=True).encode()).hexdigest(),
    }
