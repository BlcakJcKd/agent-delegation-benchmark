"""Deterministic V2.3 feature-integration task generation."""
from __future__ import annotations

import hashlib
import json
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import IGNORED_GENERATED_DIRS, IGNORED_GENERATED_SUFFIXES, SUITE_NAME, SUITE_VERSION


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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


def _write(root: Path, files: dict[str, str]) -> None:
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(value).lstrip(), encoding="utf-8")


def _verifier_script() -> str:
    return '''#!/usr/bin/env python3
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verifier.contract import checks
result = checks(Path(__file__).resolve().parents[1])
print(json.dumps({"family": "P1_snapshot_inventory", "checks": [x["passed"] for x in result], "details": result}, sort_keys=True))
sys.exit(0 if len(result) == 8 else 2)
'''


def _make(seed: int) -> TaskInstance:
    rows = [
        {"id": 101, "name": " Alpha ", "category": "hardware", "amount": 12.25, "tags": ["core"]},
        {"id": 17, "name": "beta", "category": "software", "amount": 4.5, "tags": ["edge"]},
        {"id": 63, "name": "ALPHA", "category": "hardware", "amount": 3.75, "tags": ["core", "sale"]},
        {"id": 44, "name": "Gamma", "category": "services", "amount": 8.125, "tags": ["recurring"]},
        {"id": 88, "name": "delta", "category": "software", "amount": 2.875, "tags": []},
    ]
    files = {
        "README.md": """
        # Inventory snapshots — feature request

        The existing inventory service is correct and its old API is covered by
        `tests/test_old_contract.py`. Implement the requested named snapshot
        feature without changing that old API or its invariants.

        A snapshot is a stable, named view of inventory state. A caller may
        create snapshots, query them after later mutations, serialize and
        restore them, and include them in reports. Snapshots must preserve
        normalized lookup, category filtering, ascending identifiers,
        fractional totals, and version metadata. Current-state calls remain
        the default when no snapshot is selected. The feature must work for
        multiple independent snapshots and repeated queries.

        Run the existing tests and `python verifier/verify.py`. Do not edit
        tests, verifier, task metadata, or fixture data.
        """,
        "inventory/__init__.py": "from .api import InventoryAPI\nfrom .service import InventoryService\n",
        "inventory/errors.py": """
        class InventoryError(Exception):
            \"\"\"Base error for stable public inventory failures.\"\"\"
        class UnknownProduct(InventoryError):
            pass
        class UnsupportedFeature(InventoryError):
            pass
        """,
        "inventory/snapshot.py": """
        from .errors import UnsupportedFeature

        class SnapshotRegistry:
            def __init__(self):
                self._snapshots = {}

            def capture(self, name, version, records):
                raise UnsupportedFeature("named snapshots are not in the old contract")

            def names(self):
                raise UnsupportedFeature("named snapshots are not in the old contract")

            def resolve(self, snapshot):
                raise UnsupportedFeature("named snapshots are not in the old contract")

            def restore(self, token):
                raise UnsupportedFeature("named snapshots are not in the old contract")
        """,
        "inventory/model.py": """
        from dataclasses import dataclass
        from typing import Any

        @dataclass(frozen=True)
        class Product:
            identifier: int
            name: str
            category: str
            amount: float
            tags: tuple[str, ...]

            @classmethod
            def from_record(cls, record: dict[str, Any]) -> \"Product\":
                return cls(int(record[\"id\"]), str(record[\"name\"]), str(record[\"category\"]), float(record[\"amount\"]), tuple(str(x) for x in record.get(\"tags\", ())))

            def as_record(self) -> dict[str, Any]:
                return {\"id\": self.identifier, \"name\": self.name, \"category\": self.category, \"amount\": self.amount, \"tags\": list(self.tags)}

        def clone_products(products: list[Product]) -> list[Product]:
            return [Product(p.identifier, p.name, p.category, p.amount, tuple(p.tags)) for p in products]
        """,
        "inventory/normalization.py": """
        def normalize_name(value: str) -> str:
            return \" \".join(str(value).strip().casefold().split())

        def normalize_category(value: str | None) -> str | None:
            return None if value is None else \" \".join(str(value).strip().casefold().split())

        def normalize_tags(values):
            return tuple(sorted({str(value).strip().casefold() for value in values if str(value).strip()}))
        """,
        "inventory/audit.py": """
        from .normalization import normalize_name

        def record_fingerprint(product):
            return (product.identifier, normalize_name(product.name), product.category.casefold(), float(product.amount), tuple(product.tags))

        def compare_records(before, after):
            old = {item.identifier: record_fingerprint(item) for item in before}
            new = {item.identifier: record_fingerprint(item) for item in after}
            return {\"added\": sorted(set(new) - set(old)), \"removed\": sorted(set(old) - set(new)), \"changed\": sorted(identifier for identifier in set(old) & set(new) if old[identifier] != new[identifier])}

        def change_count(before, after):
            changes = compare_records(before, after)
            return sum(len(changes[key]) for key in (\"added\", \"removed\", \"changed\"))

        def audit_summary(before, after, version):
            return {\"version\": int(version), \"changes\": compare_records(before, after), \"change_count\": change_count(before, after)}
        """,
        "inventory/metadata.py": """
        from .normalization import normalize_category, normalize_tags

        REQUIRED_FIELDS = {\"id\", \"name\", \"category\", \"amount\"}

        def validate_product_record(record):
            missing = REQUIRED_FIELDS - set(record)
            if missing:
                raise ValueError(f\"missing product fields: {sorted(missing)}\")
            if not str(record[\"name\"]).strip() or normalize_category(record[\"category\"]) is None:
                raise ValueError(\"product name and category are required\")
            amount = float(record[\"amount\"])
            if amount < 0:
                raise ValueError(\"product amount must be non-negative\")
            return {**record, \"tags\": list(normalize_tags(record.get(\"tags\", ())))}

        def public_metadata(record):
            return {\"identifier\": int(record[\"id\"]), \"category\": normalize_category(record[\"category\"]), \"tag_count\": len(record.get(\"tags\", ())) }
        """,
        "inventory/repository.py": """
        from copy import deepcopy
        from .audit import audit_summary
        from .errors import UnknownProduct
        from .metadata import validate_product_record
        from .model import Product

        class InventoryRepository:
            def __init__(self, records):
                self._products = [Product.from_record(validate_product_record(deepcopy(record))) for record in records]
                self._version = 0
                self._last_before = list(self._products)

            @property
            def version(self):
                return self._version

            def all(self):
                return list(self._products)

            def add(self, record):
                product = Product.from_record(validate_product_record(deepcopy(record)))
                if any(item.identifier == product.identifier for item in self._products):
                    raise ValueError(\"duplicate product identifier\")
                self._last_before = list(self._products)
                self._products.append(product)
                self._version += 1

            def replace(self, identifier, record):
                product = Product.from_record(validate_product_record(deepcopy(record)))
                for index, existing in enumerate(self._products):
                    if existing.identifier == int(identifier):
                        self._last_before = list(self._products)
                        self._products[index] = product
                        self._version += 1
                        return
                raise UnknownProduct(identifier)

            def remove(self, identifier):
                for index, existing in enumerate(self._products):
                    if existing.identifier == int(identifier):
                        self._last_before = list(self._products)
                        del self._products[index]
                        self._version += 1
                        return
                raise UnknownProduct(identifier)

            def export_records(self):
                return [item.as_record() for item in self._products]

            def audit(self):
                return audit_summary(self._last_before, self._products, self._version)

            def metadata(self):
                return [{"id": item.identifier, "name": item.name, "category": item.category, "amount": item.amount}
                        for item in self._products]
        """,
        "inventory/codec.py": """
        import json
        from .errors import UnsupportedFeature
        from .model import Product

        def encode_records(records, version=0):
            return json.dumps({\"version\": int(version), \"records\": [item.as_record() if isinstance(item, Product) else item for item in records]}, sort_keys=True, separators=(\",\", \":\"))

        def decode_records(payload):
            value = json.loads(payload)
            return int(value[\"version\"]), [Product.from_record(item) for item in value[\"records\"]]

        def encode_report(report):
            return json.dumps(report, sort_keys=True, separators=(\",\", \":\"))

        def decode_report(payload):
            return json.loads(payload)

        def encode_snapshot(token):
            raise UnsupportedFeature("named snapshots are not in the old contract")

        def decode_snapshot(payload):
            raise UnsupportedFeature("named snapshots are not in the old contract")
        """,
        "inventory/cache.py": """
        from .model import clone_products

        class VersionedProductCache:
            def __init__(self):
                self._entries = {}
                self.hits = 0
                self.misses = 0

            def get(self, key, version, loader):
                cache_key = (str(key), int(version))
                if cache_key in self._entries:
                    self.hits += 1
                    return clone_products(self._entries[cache_key])
                self.misses += 1
                value = clone_products(loader())
                self._entries[cache_key] = value
                return clone_products(value)

            def clear(self):
                self._entries.clear()
                self.hits = self.misses = 0

            def stats(self):
                return {\"hits\": self.hits, \"misses\": self.misses, \"entries\": len(self._entries)}
        """,
        "inventory/catalog.py": """
        from dataclasses import dataclass
        from .model import clone_products
        from .normalization import normalize_category, normalize_name

        @dataclass(frozen=True)
        class ProductQuery:
            name: str | None = None
            category: str | None = None
            required_tags: tuple[str, ...] = ()

            @classmethod
            def create(cls, name=None, category=None, required_tags=()):
                return cls(None if name is None else normalize_name(name), normalize_category(category), tuple(sorted(str(tag).strip().casefold() for tag in required_tags)))

        def select(products, query):
            return [product for product in products if (query.name is None or normalize_name(product.name) == query.name) and (query.category is None or normalize_category(product.category) == query.category) and set(query.required_tags).issubset(set(product.tags))]

        class ProductCatalog:
            def __init__(self, products):
                self._products = clone_products(products)
                self._by_name = {}
                for product in self._products:
                    self._by_name.setdefault(normalize_name(product.name), []).append(product)

            def all(self):
                return clone_products(self._products)

            def find(self, name, category=None):
                query = ProductQuery.create(name=name, category=category)
                return clone_products(select(self._products, query))

            def categories(self):
                return sorted({normalize_category(item.category) for item in self._products})
        """,
        "inventory/policy.py": """
        from .normalization import normalize_category

        def filter_category(products, category=None):
            wanted = normalize_category(category)
            if wanted is None:
                return list(products)
            return [item for item in products if normalize_category(item.category) == wanted]

        def order_products(products):
            return sorted(products, key=lambda item: item.identifier)

        def validate_report_request(category=None):
            if category is not None and not str(category).strip():
                raise ValueError(\"category must not be blank\")
            return category
        """,
        "inventory/aggregate.py": """
        from collections import defaultdict

        def summarize(products):
            products = list(products)
            total = sum(item.amount for item in products)
            by_category = defaultdict(float)
            for item in products:
                by_category[item.category.casefold()] += item.amount
            return {\"count\": len(products), \"total\": total, \"mean\": total / len(products) if products else 0.0, \"by_category\": dict(sorted(by_category.items()))}

        def summarize_names(products):
            return sorted({item.name.strip().casefold() for item in products})
        """,
        "inventory/report.py": """
        from .aggregate import summarize
        from .codec import encode_report

        def build_report(products, *, version, snapshot=None, label=\"current\"):
            ordered = sorted(products, key=lambda item: item.identifier)
            return {\"label\": label, \"version\": int(version), \"snapshot\": snapshot, \"ids\": [item.identifier for item in ordered], \"summary\": summarize(ordered)}

        def render_report(report):
            return encode_report(report)

        def build_snapshot_report(products, *, version, snapshot, label="snapshot"):
            raise NotImplementedError("snapshot reports are a new feature")
        """,
        "inventory/service.py": """
        from .aggregate import summarize
        from .cache import VersionedProductCache
        from .catalog import ProductCatalog
        from .codec import decode_snapshot, encode_records, encode_snapshot
        from .errors import UnsupportedFeature
        from .policy import filter_category, order_products, validate_report_request
        from .report import build_report, build_snapshot_report
        from .model import Product
        from .repository import InventoryRepository
        from .snapshot import SnapshotRegistry

        class InventoryService:
            def __init__(self, records):
                self.repository = InventoryRepository(records)
                self.cache = VersionedProductCache()
                self.snapshots = SnapshotRegistry()

            def _catalog(self):
                return ProductCatalog(self.cache.get(\"current\", self.repository.version, self.repository.all))

            def list_products(self, category=None):
                validate_report_request(category)
                return order_products(filter_category(self._catalog().all(), category))

            def find(self, name, category=None):
                validate_report_request(category)
                return order_products(self._catalog().find(name, category))

            def summary(self, category=None):
                return summarize(self.list_products(category))

            def report(self, category=None):
                return build_report(self.list_products(category), version=self.repository.version)

            def mutate(self, identifier, record):
                self.repository.replace(identifier, record)

            def add(self, record):
                self.repository.add(record)

            def remove(self, identifier):
                self.repository.remove(identifier)

            def export_current(self):
                return encode_records(self.repository.all(), self.repository.version)

            def metadata(self):
                return self.repository.metadata()

            def create_snapshot(self, name):
                return self.snapshots.capture(name, self.repository.version, self.repository.export_records())

            def list_snapshot_names(self):
                return self.snapshots.names()

            def list_products_at(self, snapshot, category=None):
                token = self.snapshots.resolve(snapshot)
                products = [Product.from_record(item) for item in token[\"records\"]]
                validate_report_request(category)
                return order_products(filter_category(ProductCatalog(products).all(), category))

            def export_snapshot(self, snapshot):
                return encode_snapshot(self.snapshots.resolve(snapshot))

            def restore_snapshot(self, payload):
                return self.snapshots.restore(decode_snapshot(payload))

            def snapshot_report(self, snapshot, category=None):
                token = self.snapshots.resolve(snapshot)
                validate_report_request(category)
                products = [Product.from_record(item) for item in token[\"records\"]]
                products = order_products(filter_category(ProductCatalog(products).all(), category))
                return build_snapshot_report(products, version=token[\"version\"], snapshot=token[\"name\"])
        """,
        "inventory/api.py": """
        from .service import InventoryService

        class InventoryAPI:
            def __init__(self, service: InventoryService):
                self.service = service

            def products(self, category=None):
                return self.service.list_products(category)

            def lookup(self, name, category=None):
                return self.service.find(name, category)

            def current_report(self, category=None):
                return self.service.report(category)
        """,
        "tests/test_old_contract.py": """
        import unittest
        from inventory.api import InventoryAPI
        from inventory.service import InventoryService

        RECORDS = [
            {\"id\": 101, \"name\": \" Alpha \", \"category\": \"hardware\", \"amount\": 12.25, \"tags\": [\"core\"]},
            {\"id\": 17, \"name\": \"beta\", \"category\": \"software\", \"amount\": 4.5, \"tags\": [\"edge\"]},
            {\"id\": 63, \"name\": \"ALPHA\", \"category\": \"hardware\", \"amount\": 3.75, \"tags\": [\"core\", \"sale\"]},
            {\"id\": 44, \"name\": \"Gamma\", \"category\": \"services\", \"amount\": 8.125, \"tags\": [\"recurring\"]},
            {\"id\": 88, \"name\": \"delta\", \"category\": \"software\", \"amount\": 2.875, \"tags\": []},
        ]

        class OldContract(unittest.TestCase):
            def test_old_listing_order_and_fractional_summary(self):
                service = InventoryService(RECORDS)
                self.assertEqual([x.identifier for x in service.list_products()], [17, 44, 63, 88, 101])
                self.assertAlmostEqual(service.summary()[\"total\"], 31.5)

            def test_old_normalized_lookup_and_category_filter(self):
                service = InventoryService(RECORDS)
                self.assertEqual([x.identifier for x in service.find(\" alpha \")], [63, 101])
                self.assertEqual([x.identifier for x in service.find(\"ALPHA\", \"hardware\")], [63, 101])

            def test_old_api_wrapper_and_mutation(self):
                service = InventoryService(RECORDS); api = InventoryAPI(service)
                self.assertEqual([x.identifier for x in api.products(\"software\")], [17, 88])
                service.mutate(17, {**RECORDS[1], \"amount\": 7.5})
                self.assertAlmostEqual(service.summary()[\"total\"], 34.5)

        if __name__ == \"__main__\": unittest.main()
        """,
        "tests/test_contract.py": "from inventory.service import InventoryService\ndef test_import(): assert InventoryService\n",
        "data/products.json": json.dumps(rows, indent=2),
    }
    scope = {"editable": ["inventory/**/*.py"], "immutable": ["README.md", "tests/**", "verifier/**", ".ekalavya/**", "data/**"], "generated_ignored": [".pytest_cache/**", "__pycache__/**", "*.pyc"]}
    names = ["snapshot creation", "snapshot stability", "independent snapshots", "snapshot cache and lookup", "snapshot category scope", "snapshot serialization", "snapshot reporting", "old API compatibility"]
    specification = {"suite": SUITE_NAME, "version": SUITE_VERSION, "family": "P1_snapshot_inventory", "seed": seed, "requirements": ["stable named views across mutations", "multiple independent snapshots", "backward-compatible current API", "serialization and report propagation"], "checks": names, "evaluation_contract": "Eight independent behavioral checks; old contract tests must remain green and visible/controller new-feature checks must agree."}
    files["verifier/contract.py"] = CONTRACT
    files["verifier/verify.py"] = _verifier_script()
    files[".ekalavya/edit-scope.json"] = json.dumps(scope, indent=2, sort_keys=True)
    files[".ekalavya/task.json"] = json.dumps({"suite": SUITE_NAME, "version": SUITE_VERSION, "family": "P1_snapshot_inventory", "seed": seed}, sort_keys=True)
    return TaskInstance("P1_snapshot_inventory", seed, "Implement the named inventory snapshot feature described in the README. Preserve the complete existing API and old-contract behavior while adding stable multi-snapshot querying, state evolution, serialization, and reporting.", files, specification, scope, files["verifier/verify.py"])


CONTRACT = """import json
def _safe(name, fn):
 try: return {\"name\":name,\"passed\":bool(fn()),\"detail\":\"\"}
 except Exception as exc: return {\"name\":name,\"passed\":False,\"detail\":type(exc).__name__}
def _records(root): return json.loads((root/\"data/products.json\").read_text())
def checks(root):
 from inventory.service import InventoryService
 records=_records(root)
 def c1():
  s=InventoryService(records); token=s.create_snapshot(\"baseline\"); return token[\"name\"]==\"baseline\" and [x.identifier for x in s.list_products_at(token)]==[17,44,63,88,101]
 def c2():
  s=InventoryService(records); token=s.create_snapshot(\"before\"); s.mutate(101,{**records[0],\"amount\":20.25}); return s.summary()[\"total\"]==39.5 and s.snapshot_report(token)[\"summary\"][\"total\"]==31.5
 def c3():
  s=InventoryService(records); one=s.create_snapshot(\"one\"); s.add({\"id\":120,\"name\":\"epsilon\",\"category\":\"hardware\",\"amount\":1.25,\"tags\":[]}); two=s.create_snapshot(\"two\"); return len(s.list_products_at(one))==5 and len(s.list_products_at(two))==6 and {x[\"name\"] for x in s.list_snapshot_names()}=={\"one\",\"two\"}
 def c4():
  s=InventoryService(records); token=s.create_snapshot(\"lookup\"); first=s.list_products_at(token); second=s.list_products_at(token); return [x.identifier for x in s.find(\" alpha \",\"hardware\")] == [63,101] and [x.identifier for x in first]==[x.identifier for x in second]
 def c5():
  s=InventoryService(records); token=s.create_snapshot(\"scope\"); return [x.identifier for x in s.list_products_at(token,\"software\")] == [17,88] and s.snapshot_report(token,\"hardware\")[\"summary\"][\"count\"]==2
 def c6():
  s=InventoryService(records); token=s.create_snapshot(\"wire\"); payload=s.export_snapshot(token); restored=s.restore_snapshot(payload); return restored[\"name\"]==\"wire\" and restored[\"version\"]==0 and len(s.list_products_at(restored))==5
 def c7():
  s=InventoryService(records); token=s.create_snapshot(\"report\"); report=s.snapshot_report(token); return report[\"snapshot\"]==\"report\" and report[\"version\"]==0 and report[\"ids\"]==[17,44,63,88,101] and report[\"summary\"][\"by_category\"][\"hardware\"]==16.0
 def c8():
  s=InventoryService(records); token=s.create_snapshot(\"compat\"); before=s.report(); s.mutate(17,{**records[1],\"amount\":7.5}); return before[\"ids\"]==[17,44,63,88,101] and s.report()[\"version\"]==1 and s.list_products_at(token)[0].amount==4.5
 return [_safe(\"snapshot creation\",c1),_safe(\"snapshot stability\",c2),_safe(\"independent snapshots\",c3),_safe(\"snapshot cache and lookup\",c4),_safe(\"snapshot category scope\",c5),_safe(\"snapshot serialization\",c6),_safe(\"snapshot reporting\",c7),_safe(\"old API compatibility\",c8)]
"""


def make_instance(family: str, seed: int) -> TaskInstance:
    if family != "P1_snapshot_inventory":
        raise ValueError(f"unknown V2.3 family: {family}")
    return _make(seed)


def materialize(instance: TaskInstance, workspace: Path) -> Path:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    _write(workspace, instance.files)
    return workspace


def workspace_digest(workspace: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in workspace.rglob("*") if p.is_file() and p.suffix not in IGNORED_GENERATED_SUFFIXES and not any(x in IGNORED_GENERATED_DIRS for x in p.parts)):
        digest.update(path.relative_to(workspace).as_posix().encode()); digest.update(b"\0"); digest.update(path.read_bytes())
    return digest.hexdigest()
