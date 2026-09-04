"""Deterministic V2.4 repository-scale task generation.

The generated application is correct for its pre-existing ticket-management
contract.  The requested bookmark feature is deliberately absent: there are
no feature-named placeholders or forwarding methods in the baseline.
"""
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


def _dedent(value: str) -> str:
    return textwrap.dedent(value).lstrip()


BASE_FILES: dict[str, str] = {
    "dispatchboard/__init__.py": """
        from .api import WorkspaceAPI
        from .model import Project, Ticket, User
        from .service import WorkspaceService

        __all__ = ["Project", "Ticket", "User", "WorkspaceAPI", "WorkspaceService"]
    """,
    "dispatchboard/errors.py": """
        class WorkspaceError(Exception):
            \"\"\"Base class for stable workspace failures.\"\"\"

        class ValidationError(WorkspaceError):
            pass

        class MissingRecord(WorkspaceError):
            pass

        class DuplicateRecord(WorkspaceError):
            pass

        class PermissionDenied(WorkspaceError):
            pass

        class InvalidPayload(WorkspaceError):
            pass
    """,
    "dispatchboard/common.py": """
        import copy
        import json
        from collections.abc import Iterable

        def clone(value):
            return copy.deepcopy(value)

        def stable_json(value):
            return json.dumps(value, sort_keys=True, separators=(\",\", \":\"))

        def clean_text(value, field):
            text = \" \".join(str(value).strip().split())
            if not text:
                raise ValueError(f\"{field} must not be blank\")
            return text

        def optional_text(value):
            if value is None:
                return None
            text = \" \".join(str(value).strip().split())
            return text or None

        def unique_strings(values):
            if values is None:
                return ()
            result = {\" \".join(str(item).strip().casefold().split()) for item in values}
            return tuple(sorted(item for item in result if item))

        def as_list(values):
            return list(values) if isinstance(values, Iterable) and not isinstance(values, (str, bytes, dict)) else []

        def safe_int(value, field):
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f\"{field} must be an integer\") from exc

        def safe_float(value, field):
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f\"{field} must be numeric\") from exc
            if number != number or number in (float(\"inf\"), float(\"-inf\")):
                raise ValueError(f\"{field} must be finite\")
            return number

        def ordered_dict(items):
            return {key: items[key] for key in sorted(items)}

        def partition(values, predicate):
            yes, no = [], []
            for value in values:
                (yes if predicate(value) else no).append(value)
            return yes, no

        def pairwise(values):
            values = list(values)
            return list(zip(values, values[1:]))

        def ensure_mapping(value, field):
            if not isinstance(value, dict):
                raise ValueError(f\"{field} must be an object\")
            return value
    """,
    "dispatchboard/model.py": """
        from dataclasses import dataclass
        from typing import Any

        from .common import clean_text, safe_float, safe_int, unique_strings
        from .identifiers import canonical_key, canonical_labels, canonical_name

        @dataclass(frozen=True)
        class User:
            key: str
            display_name: str
            role: str

            @classmethod
            def from_record(cls, record: dict[str, Any]) -> \"User\":
                return cls(canonical_key(record[\"key\"], \"user key\"), canonical_name(record[\"display_name\"], \"display name\"), canonical_key(record[\"role\"], \"role\"))

            def as_record(self) -> dict[str, Any]:
                return {\"key\": self.key, \"display_name\": self.display_name, \"role\": self.role}

        @dataclass(frozen=True)
        class Project:
            key: str
            name: str
            owner: str
            labels: tuple[str, ...]

            @classmethod
            def from_record(cls, record: dict[str, Any]) -> \"Project\":
                return cls(canonical_key(record[\"key\"], \"project key\"), canonical_name(record[\"name\"], \"project name\"), canonical_key(record[\"owner\"], \"project owner\"), canonical_labels(record.get(\"labels\", ())))

            def as_record(self) -> dict[str, Any]:
                return {\"key\": self.key, \"name\": self.name, \"owner\": self.owner, \"labels\": list(self.labels)}

        @dataclass(frozen=True)
        class Ticket:
            identifier: int
            project: str
            title: str
            status: str
            owner: str
            priority: int
            estimate: float
            labels: tuple[str, ...]
            created_day: int

            @classmethod
            def from_record(cls, record: dict[str, Any]) -> \"Ticket\":
                return cls(safe_int(record[\"id\"], \"ticket id\"), canonical_key(record[\"project\"], \"project\"), canonical_name(record[\"title\"], \"title\"), canonical_key(record[\"status\"], \"status\"), canonical_key(record[\"owner\"], \"owner\"), safe_int(record[\"priority\"], \"priority\"), safe_float(record[\"estimate\"], \"estimate\"), canonical_labels(record.get(\"labels\", ())), safe_int(record[\"created_day\"], \"created day\"))

            def as_record(self) -> dict[str, Any]:
                return {\"id\": self.identifier, \"project\": self.project, \"title\": self.title, \"status\": self.status, \"owner\": self.owner, \"priority\": self.priority, \"estimate\": self.estimate, \"labels\": list(self.labels), \"created_day\": self.created_day}

            def with_changes(self, changes: dict[str, Any]) -> \"Ticket\":
                data = self.as_record()
                data.update(changes)
                data[\"id\"] = self.identifier
                return Ticket.from_record(data)

        def clone_tickets(values):
            return [Ticket(item.identifier, item.project, item.title, item.status, item.owner, item.priority, item.estimate, tuple(item.labels), item.created_day) for item in values]
    """,
    "dispatchboard/normalization.py": """
        from .common import optional_text, unique_strings

        STATUS_ALIASES = {\"open\": \"open\", \"opened\": \"open\", \"active\": \"open\", \"in progress\": \"open\", \"closed\": \"closed\", \"done\": \"closed\", \"resolved\": \"closed\", \"blocked\": \"blocked\"}

        def normalize_status(value):
            text = \" \".join(str(value).strip().casefold().split())
            return STATUS_ALIASES.get(text, text)

        def normalize_owner(value):
            text = optional_text(value)
            return text.casefold() if text else None

        def normalize_project(value):
            text = optional_text(value)
            return text.casefold() if text else None

        def normalize_title(value):
            return \" \".join(str(value).strip().casefold().split())

        def normalize_labels(values):
            return unique_strings(values)

        def normalize_query_values(status=None, owner=None, project=None, labels=()):
            return {\"status\": normalize_status(status) if status is not None else None, \"owner\": normalize_owner(owner), \"project\": normalize_project(project), \"labels\": normalize_labels(labels)}
    """,
    "dispatchboard/records.py": """
        from .errors import ValidationError
        from .checks import check_invariants
        from .identifiers import ensure_unique
        from .model import Project, Ticket, User

        def validate_users(records):
            users = [User.from_record(record) for record in records]
            ensure_unique([item.key for item in users], \"user key\")
            return users

        def validate_projects(records, users):
            known = {item.key for item in users}
            projects = [Project.from_record(record) for record in records]
            ensure_unique([item.key for item in projects], \"project key\")
            if any(item.owner not in known for item in projects):
                raise ValidationError(\"project owner is unknown\")
            return projects

        def validate_tickets(records, projects, users):
            project_keys = {item.key for item in projects}
            user_keys = {item.key for item in users}
            tickets = [Ticket.from_record(record) for record in records]
            ensure_unique([item.identifier for item in tickets], \"ticket id\")
            if any(item.project not in project_keys for item in tickets):
                raise ValidationError(\"ticket project is unknown\")
            if any(item.owner not in user_keys for item in tickets):
                raise ValidationError(\"ticket owner is unknown\")
            if any(item.priority < 1 or item.priority > 5 for item in tickets):
                raise ValidationError(\"priority must be between one and five\")
            if any(item.estimate < 0 for item in tickets):
                raise ValidationError(\"estimate must be non-negative\")
            return tickets

        def validate_bundle(bundle):
            if not isinstance(bundle, dict):
                raise ValidationError(\"bundle must be an object\")
            for field in (\"users\", \"projects\", \"tickets\"):
                if not isinstance(bundle.get(field), list):
                    raise ValidationError(f\"bundle.{field} must be a list\")
            users = validate_users(bundle[\"users\"])
            projects = validate_projects(bundle[\"projects\"], users)
            tickets = validate_tickets(bundle[\"tickets\"], projects, users)
            check_invariants(users, projects, tickets)
            return users, projects, tickets
    """,
    "dispatchboard/identifiers.py": """
        import re

        from .errors import ValidationError

        _KEY = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")

        def canonical_key(value, field="key"):
            text = " ".join(str(value).strip().casefold().split())
            text = text.replace(" ", "-")
            if not text or not _KEY.fullmatch(text):
                raise ValidationError(f"{field} has an invalid identifier")
            return text

        def canonical_name(value, field="name"):
            text = " ".join(str(value).strip().split())
            if not text:
                raise ValidationError(f"{field} must not be blank")
            return text

        def ensure_unique(values, field="key"):
            values = list(values)
            if len(values) != len(set(values)):
                raise ValidationError(f"duplicate {field}")
            return values

        def parse_identifier(value, field="identifier"):
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{field} must be an integer") from exc
            if number < 0:
                raise ValidationError(f"{field} must be non-negative")
            return number

        def canonical_labels(values):
            if values is None:
                return ()
            if isinstance(values, (str, bytes, dict)):
                raise ValidationError("labels must be a sequence")
            labels = []
            for value in values:
                label = " ".join(str(value).strip().casefold().split())
                if label and label not in labels:
                    labels.append(label)
            return tuple(sorted(labels))

        def compare_keys(left, right):
            return canonical_key(left) == canonical_key(right)

        def sorted_unique(values):
            return sorted(set(canonical_key(value) for value in values))
    """,
    "dispatchboard/validation.py": """
        from collections.abc import Mapping

        from .errors import ValidationError

        def require_mapping(value, field):
            if not isinstance(value, Mapping):
                raise ValidationError(f"{field} must be a mapping")
            return dict(value)

        def require_fields(value, fields, field="record"):
            value = require_mapping(value, field)
            missing = [name for name in fields if name not in value]
            if missing:
                raise ValidationError(f"{field} missing fields: {', '.join(missing)}")
            return value

        def reject_unknown_fields(value, fields, field="record"):
            value = require_mapping(value, field)
            unknown = sorted(set(value) - set(fields))
            if unknown:
                raise ValidationError(f"{field} has unknown fields: {', '.join(unknown)}")
            return value

        def bounded_integer(value, field, *, minimum=None, maximum=None):
            try:
                result = int(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{field} must be an integer") from exc
            if minimum is not None and result < minimum:
                raise ValidationError(f"{field} is below its minimum")
            if maximum is not None and result > maximum:
                raise ValidationError(f"{field} is above its maximum")
            return result

        def bounded_number(value, field, *, minimum=None):
            try:
                result = float(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{field} must be numeric") from exc
            if result != result or result in (float("inf"), float("-inf")):
                raise ValidationError(f"{field} must be finite")
            if minimum is not None and result < minimum:
                raise ValidationError(f"{field} is below its minimum")
            return result

        def validate_page_request(limit, offset):
            return bounded_integer(limit, "limit", minimum=1, maximum=1000), bounded_integer(offset, "offset", minimum=0)

        def validate_sort_order(value):
            value = str(value).strip().casefold()
            if value not in {"ascending", "descending"}:
                raise ValidationError("sort order must be ascending or descending")
            return value

        def validate_nonempty(values, field):
            values = list(values)
            if not values:
                raise ValidationError(f"{field} must not be empty")
            return values
    """,
    "dispatchboard/collections.py": """
        from dataclasses import dataclass
        from typing import Generic, Iterable, Iterator, TypeVar

        T = TypeVar("T")

        @dataclass(frozen=True)
        class Page(Generic[T]):
            items: tuple[T, ...]
            limit: int
            offset: int
            total: int

            @property
            def has_next(self):
                return self.offset + len(self.items) < self.total

            @property
            def has_previous(self):
                return self.offset > 0

            def as_record(self):
                return {"items": list(self.items), "limit": self.limit, "offset": self.offset, "total": self.total}

        def make_page(values: Iterable[T], limit: int, offset: int) -> Page[T]:
            values = list(values)
            return Page(tuple(values[offset:offset + limit]), int(limit), int(offset), len(values))

        def chunks(values: Iterable[T], size: int) -> Iterator[tuple[T, ...]]:
            batch = []
            for value in values:
                batch.append(value)
                if len(batch) == size:
                    yield tuple(batch)
                    batch = []
            if batch:
                yield tuple(batch)

        def distinct_by(values: Iterable[T], key):
            seen = set()
            result = []
            for value in values:
                marker = key(value)
                if marker not in seen:
                    seen.add(marker)
                    result.append(value)
            return result

        def group_by(values: Iterable[T], key):
            groups = {}
            for value in values:
                groups.setdefault(key(value), []).append(value)
            return groups

        def flatten(groups):
            return [value for values in groups.values() for value in values]
    """,
    "dispatchboard/checks.py": """
        from .errors import ValidationError

        def check_invariants(users, projects, tickets):
            user_keys = {user.key for user in users}
            project_keys = {project.key for project in projects}
            ticket_ids = [ticket.identifier for ticket in tickets]
            if len(ticket_ids) != len(set(ticket_ids)):
                raise ValidationError("ticket identifiers must be unique")
            if any(project.owner not in user_keys for project in projects):
                raise ValidationError("project owner is unknown")
            if any(ticket.project not in project_keys or ticket.owner not in user_keys for ticket in tickets):
                raise ValidationError("ticket relationship is unknown")
            if any(ticket.priority not in range(1, 6) for ticket in tickets):
                raise ValidationError("ticket priority is outside the allowed range")
            return True

        def check_revision_sequence(history):
            numbers = [int(item["number"]) for item in history]
            return bool(numbers) and numbers[0] == 0 and numbers == list(range(numbers[-1] + 1))

        def check_event_sequence(events):
            revisions = [int(event.revision) for event in events]
            return revisions == sorted(revisions)

        def check_report_shape(report):
            required = {"title", "revision", "ids", "summary", "status_counts", "priority_distribution", "projects", "query"}
            return required.issubset(report) and isinstance(report["ids"], list) and isinstance(report["summary"], dict)

        def check_round_trip(first, second):
            return first == second

        def check_monotonic_revision(before, after):
            return int(after) >= int(before)

        def check_known_keys(values, known):
            return all(value in set(known) for value in values)

        def check_nonnegative_estimates(tickets):
            return all(float(ticket.estimate) >= 0 for ticket in tickets)
    """,
    "dispatchboard/storage.py": """
        from .common import clone
        from .errors import DuplicateRecord, MissingRecord

        class RecordStore:
            def __init__(self, records):
                self._records = {int(item[\"id\"]): clone(item) for item in records}
                self._revision = 0

            @property
            def revision(self):
                return self._revision

            def all(self):
                return [clone(self._records[key]) for key in sorted(self._records)]

            def get(self, identifier):
                key = int(identifier)
                if key not in self._records:
                    raise MissingRecord(key)
                return clone(self._records[key])

            def add(self, record):
                key = int(record[\"id\"])
                if key in self._records:
                    raise DuplicateRecord(key)
                self._records[key] = clone(record)
                self._revision += 1

            def replace(self, identifier, record):
                key = int(identifier)
                if key not in self._records:
                    raise MissingRecord(key)
                candidate = clone(record)
                candidate[\"id\"] = key
                self._records[key] = candidate
                self._revision += 1

            def remove(self, identifier):
                key = int(identifier)
                if key not in self._records:
                    raise MissingRecord(key)
                del self._records[key]
                self._revision += 1

            def export(self):
                return {\"revision\": self._revision, \"records\": self.all()}

            def restore(self, payload):
                self._records = {int(item[\"id\"]): clone(item) for item in payload[\"records\"]}
                self._revision = int(payload.get(\"revision\", 0))

            def contains(self, identifier):
                return int(identifier) in self._records

            def count(self):
                return len(self._records)

            def ids(self):
                return tuple(sorted(self._records))

            def snapshot_at(self, revision=None):
                if revision is not None and int(revision) != self._revision:
                    raise ValueError(\"record snapshot revision is not current\")
                return {\"revision\": self._revision, \"records\": self.all()}

            def replace_all(self, records, revision=None):
                records = list(records)
                candidate = {int(item[\"id\"]): clone(item) for item in records}
                if len(candidate) != len(records):
                    raise ValueError(\"duplicate record identifier\")
                self._records = candidate
                if revision is not None:
                    self._revision = int(revision)

            def changed_ids(self, before):
                previous = {int(item[\"id\"]): item for item in before}
                current = {int(item[\"id\"]): item for item in self.all()}
                return {\"added\": sorted(set(current) - set(previous)), \"removed\": sorted(set(previous) - set(current)), \"retained\": sorted(set(previous) & set(current))}

            def map(self, function):
                return [function(item) for item in self.all()]

            def values_between(self, lower, upper):
                return [item for item in self.all() if int(lower) <= int(item[\"id\"]) <= int(upper)]

            def export_ids(self, identifiers):
                return [self.get(identifier) for identifier in sorted(set(identifiers))]

            def replace_if_present(self, identifier, record):
                if not self.contains(identifier):
                    return False
                self.replace(identifier, record)
                return True

            def revision_matches(self, revision):
                return int(revision) == self._revision

            def transaction(self):
                return _StoreTransaction(self)

        class _StoreTransaction:
            def __init__(self, store):
                self.store = store
                self.before = store.export()
                self.committed = False

            def __enter__(self):
                return self

            def commit(self):
                self.committed = True
                return self.store.revision

            def rollback(self):
                self.store.restore(self.before)
                self.committed = False

            def __exit__(self, error_type, error, traceback):
                if error_type is not None or not self.committed:
                    self.rollback()
                return False
    """,
    "dispatchboard/versioning.py": """
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class Revision:
            number: int
            reason: str

        class RevisionClock:
            def __init__(self):
                self._history = [Revision(0, \"initial\")]

            @property
            def current(self):
                return self._history[-1].number

            def advance(self, reason):
                revision = Revision(self.current + 1, str(reason))
                self._history.append(revision)
                return revision

            def history(self):
                return list(self._history)

            def describe(self):
                return [{\"number\": item.number, \"reason\": item.reason} for item in self._history]

            def restore(self, entries):
                self._history = [Revision(int(item[\"number\"]), str(item[\"reason\"])) for item in entries] or [Revision(0, \"initial\")]
    """,
    "dispatchboard/query.py": """
        from dataclasses import dataclass

        from .common import optional_text, unique_strings
        from .normalization import normalize_owner, normalize_project, normalize_status

        @dataclass(frozen=True)
        class TicketQuery:
            status: str | None = None
            owner: str | None = None
            project: str | None = None
            labels: tuple[str, ...] = ()
            text: str | None = None

            @classmethod
            def create(cls, *, status=None, owner=None, project=None, labels=(), text=None):
                return cls(normalize_status(status) if status is not None else None, normalize_owner(owner), normalize_project(project), unique_strings(labels), optional_text(text).casefold() if optional_text(text) else None)

            def matches(self, ticket):
                if self.status is not None and ticket.status != self.status:
                    return False
                if self.owner is not None and ticket.owner != self.owner:
                    return False
                if self.project is not None and ticket.project != self.project:
                    return False
                if not set(self.labels).issubset(set(ticket.labels)):
                    return False
                if self.text is not None and self.text not in ticket.title.casefold():
                    return False
                return True

            def as_mapping(self):
                return {\"status\": self.status, \"owner\": self.owner, \"project\": self.project, \"labels\": list(self.labels), \"text\": self.text}

            @classmethod
            def from_mapping(cls, mapping):
                return cls.create(**dict(mapping))

        def apply_query(tickets, query):
            return [ticket for ticket in tickets if query.matches(ticket)]

        def sort_tickets(tickets):
            return sorted(tickets, key=lambda item: (item.priority, item.created_day, item.identifier))

        def query_summary(query):
            return query.as_mapping()
    """,
    "dispatchboard/index.py": """
        from collections import defaultdict

        from .model import clone_tickets
        from .normalization import normalize_labels

        class TicketIndex:
            def __init__(self):
                self.by_status = defaultdict(set)
                self.by_owner = defaultdict(set)
                self.by_project = defaultdict(set)
                self.by_label = defaultdict(set)

            def rebuild(self, tickets):
                self.by_status.clear(); self.by_owner.clear(); self.by_project.clear(); self.by_label.clear()
                for ticket in tickets:
                    self.add(ticket)

            def add(self, ticket):
                identifier = ticket.identifier
                self.by_status[ticket.status].add(identifier)
                self.by_owner[ticket.owner].add(identifier)
                self.by_project[ticket.project].add(identifier)
                for label in normalize_labels(ticket.labels):
                    self.by_label[label].add(identifier)

            def remove(self, ticket):
                identifier = ticket.identifier
                for bucket in (self.by_status[ticket.status], self.by_owner[ticket.owner], self.by_project[ticket.project]):
                    bucket.discard(identifier)
                for label in normalize_labels(ticket.labels):
                    self.by_label[label].discard(identifier)

            def candidates(self, *, status=None, owner=None, project=None, labels=()):
                buckets = []
                if status is not None: buckets.append(self.by_status.get(status, set()))
                if owner is not None: buckets.append(self.by_owner.get(owner, set()))
                if project is not None: buckets.append(self.by_project.get(project, set()))
                buckets.extend(self.by_label.get(label, set()) for label in normalize_labels(labels))
                if not buckets:
                    return None
                return set.intersection(*(set(bucket) for bucket in buckets))

            def stats(self):
                return {\"statuses\": len(self.by_status), \"owners\": len(self.by_owner), \"projects\": len(self.by_project), \"labels\": len(self.by_label)}

        def index_ticket_ids(index, tickets, query):
            ids = index.candidates(status=query.status, owner=query.owner, project=query.project, labels=query.labels)
            if ids is None:
                return clone_tickets(tickets)
            return [ticket for ticket in clone_tickets(tickets) if ticket.identifier in ids]
    """,
    "dispatchboard/policy.py": """
        from .errors import PermissionDenied, ValidationError
        from .normalization import normalize_owner, normalize_status
        from .validation import validate_page_request

        VALID_STATUSES = {\"open\", \"closed\", \"blocked\"}

        def check_status(status):
            value = normalize_status(status)
            if value not in VALID_STATUSES:
                raise ValidationError(f\"unknown status: {status}\")
            return value

        def check_owner(owner, users):
            value = normalize_owner(owner)
            if value not in {user.key for user in users}:
                raise ValidationError(f\"unknown owner: {owner}\")
            return value

        def can_edit(user, ticket, users):
            actor = next((item for item in users if item.key == normalize_owner(user)), None)
            if actor is None:
                raise PermissionDenied(user)
            return actor.role in {\"admin\", \"lead\"} or actor.key == ticket.owner

        def validate_page(limit, offset):
            try:
                return validate_page_request(limit, offset)
            except ValidationError:
                raise
            except (TypeError, ValueError) as exc:
                raise ValidationError(\"invalid page request\") from exc

        def paginate(items, limit=100, offset=0):
            limit, offset = validate_page(limit, offset)
            return list(items)[offset:offset + limit]
    """,
    "dispatchboard/metrics.py": """
        from collections import defaultdict

        def _round(value):
            return round(float(value), 6)

        def summarize(tickets):
            items = list(tickets)
            total = sum(item.estimate for item in items)
            by_status = defaultdict(float)
            by_owner = defaultdict(float)
            by_project = defaultdict(float)
            for item in items:
                by_status[item.status] += item.estimate
                by_owner[item.owner] += item.estimate
                by_project[item.project] += item.estimate
            return {\"count\": len(items), \"estimate\": _round(total), \"mean_priority\": _round(sum(item.priority for item in items) / len(items)) if items else 0.0, \"by_status\": {key: _round(by_status[key]) for key in sorted(by_status)}, \"by_owner\": {key: _round(by_owner[key]) for key in sorted(by_owner)}, \"by_project\": {key: _round(by_project[key]) for key in sorted(by_project)}}

        def status_counts(tickets):
            result = defaultdict(int)
            for item in tickets:
                result[item.status] += 1
            return dict(sorted(result.items()))

        def priority_distribution(tickets):
            result = defaultdict(int)
            for item in tickets:
                result[str(item.priority)] += 1
            return dict(sorted(result.items(), key=lambda pair: int(pair[0])))

        def project_rollup(tickets):
            result = defaultdict(lambda: {\"count\": 0, \"estimate\": 0.0})
            for item in tickets:
                result[item.project][\"count\"] += 1
                result[item.project][\"estimate\"] += item.estimate
            return {key: {\"count\": value[\"count\"], \"estimate\": _round(value[\"estimate\"])} for key, value in sorted(result.items())}
    """,
    "dispatchboard/codec.py": """
        import json

        from .errors import InvalidPayload

        SCHEMA = \"dispatchboard.bundle.v1\"

        def encode_bundle(users, projects, tickets, history):
            value = {\"schema\": SCHEMA, \"users\": [item.as_record() for item in users], \"projects\": [item.as_record() for item in projects], \"tickets\": [item.as_record() for item in tickets], \"history\": list(history)}
            return json.dumps(value, sort_keys=True, separators=(\",\", \":\"))

        def decode_bundle(payload):
            try:
                value = json.loads(payload)
            except (TypeError, ValueError) as exc:
                raise InvalidPayload(\"bundle is not valid JSON\") from exc
            if not isinstance(value, dict) or value.get(\"schema\") != SCHEMA:
                raise InvalidPayload(\"unsupported bundle schema\")
            return value

        def encode_ticket(ticket):
            return json.dumps(ticket.as_record(), sort_keys=True, separators=(\",\", \":\"))

        def decode_ticket(payload):
            try:
                value = json.loads(payload)
            except (TypeError, ValueError) as exc:
                raise InvalidPayload(\"ticket is not valid JSON\") from exc
            return value

        def encode_history(entries):
            return json.dumps(list(entries), sort_keys=True, separators=(\",\", \":\"))

        def decode_history(payload):
            value = json.loads(payload)
            if not isinstance(value, list):
                raise InvalidPayload(\"history must be a list\")
            return value
    """,
    "dispatchboard/audit.py": """
        from .common import stable_json

        def fingerprint(ticket):
            return stable_json(ticket.as_record())

        def diff(before, after):
            old = {item.identifier: fingerprint(item) for item in before}
            new = {item.identifier: fingerprint(item) for item in after}
            return {\"added\": sorted(set(new) - set(old)), \"removed\": sorted(set(old) - set(new)), \"changed\": sorted(key for key in set(old) & set(new) if old[key] != new[key])}

        def diff_count(changes):
            return sum(len(changes[key]) for key in (\"added\", \"removed\", \"changed\"))

        def audit_event(before, after, revision, reason):
            changes = diff(before, after)
            return {\"revision\": int(revision), \"reason\": str(reason), \"changes\": changes, \"change_count\": diff_count(changes)}

        def audit_series(events):
            return {\"events\": len(list(events)), \"revisions\": [item.get(\"revision\") for item in events]}
    """,
    "dispatchboard/events.py": """
        from dataclasses import dataclass
        from datetime import datetime, timezone

        @dataclass(frozen=True)
        class Event:
            kind: str
            revision: int
            actor: str
            payload: dict
            occurred_at: str

            def as_record(self):
                return {\"kind\": self.kind, \"revision\": self.revision, \"actor\": self.actor, \"payload\": self.payload, \"occurred_at\": self.occurred_at}

        class EventLog:
            def __init__(self):
                self._events = []

            def append(self, kind, revision, actor, payload):
                event = Event(str(kind), int(revision), str(actor), dict(payload), datetime.now(timezone.utc).isoformat())
                self._events.append(event)
                return event

            def all(self):
                return list(self._events)

            def by_kind(self, kind):
                return [item for item in self._events if item.kind == kind]

            def export(self):
                return [item.as_record() for item in self._events]

            def restore(self, values):
                self._events = [Event(item[\"kind\"], int(item[\"revision\"]), item[\"actor\"], dict(item[\"payload\"]), item[\"occurred_at\"]) for item in values]
    """,
    "dispatchboard/repository.py": """
        from .common import clone
        from .index import TicketIndex
        from .model import Ticket, clone_tickets
        from .normalization import normalize_owner, normalize_project, normalize_status
        from .query import TicketQuery, apply_query, sort_tickets
        from .records import validate_bundle, validate_tickets
        from .storage import RecordStore
        from .versioning import RevisionClock

        class TicketRepository:
            def __init__(self, records, projects, users):
                self.users = list(users)
                self.projects = list(projects)
                self._store = RecordStore(records)
                self.clock = RevisionClock()
                self.index = TicketIndex()
                self._rebuild()

            def _rebuild(self):
                self._tickets = [Ticket.from_record(item) for item in self._store.all()]
                self.index.rebuild(self._tickets)

            @property
            def revision(self):
                return self.clock.current

            def all(self):
                return clone_tickets(self._tickets)

            def find(self, query):
                candidates = self.index.candidates(status=query.status, owner=query.owner, project=query.project, labels=query.labels)
                values = self._tickets if candidates is None else [item for item in self._tickets if item.identifier in candidates]
                return sort_tickets(apply_query(values, query))

            def get(self, identifier):
                return Ticket.from_record(self._store.get(identifier))

            def add(self, record, actor=\"system\"):
                candidate = Ticket.from_record(record)
                validate_tickets([candidate.as_record()], self.projects, self.users)
                self._store.add(candidate.as_record()); revision = self.clock.advance(f\"add:{candidate.identifier}\"); self._rebuild(); return revision.number

            def update(self, identifier, changes, actor=\"system\"):
                current = self.get(identifier); candidate = current.with_changes(changes)
                validate_tickets([candidate.as_record()], self.projects, self.users)
                self._store.replace(identifier, candidate.as_record()); revision = self.clock.advance(f\"update:{identifier}\"); self._rebuild(); return revision.number

            def remove(self, identifier, actor=\"system\"):
                self._store.remove(identifier); revision = self.clock.advance(f\"remove:{identifier}\"); self._rebuild(); return revision.number

            def bundle(self):
                return {\"users\": [item.as_record() for item in self.users], \"projects\": [item.as_record() for item in self.projects], \"tickets\": [item.as_record() for item in self._tickets], \"history\": self.clock.describe()}

            def replace_bundle(self, bundle):
                users, projects, tickets = validate_bundle(bundle)
                self.users, self.projects = users, projects
                self._store = RecordStore([item.as_record() for item in tickets])
                self.clock.restore(bundle.get(\"history\", [])); self._rebuild()

            def project_keys(self):
                return sorted(item.key for item in self.projects)

            def owner_keys(self):
                return sorted(item.key for item in self.users)
    """,
    "dispatchboard/report.py": """
        from .metrics import priority_distribution, project_rollup, status_counts, summarize
        from .checks import check_report_shape

        def make_report(tickets, *, revision, title=\"current\", query=None):
            items = list(tickets)
            report = {\"title\": title, \"revision\": int(revision), \"ids\": [item.identifier for item in items], \"summary\": summarize(items), \"status_counts\": status_counts(items), \"priority_distribution\": priority_distribution(items), \"projects\": project_rollup(items), \"query\": query}
            if not check_report_shape(report):
                raise ValueError(\"report is missing required fields\")
            return report

        def render_text(report):
            summary = report[\"summary\"]
            return f\"{report['title']}@{report['revision']}: {summary['count']} tickets / {summary['estimate']:.2f} estimate\"

        def report_headers(report):
            return [\"title\", \"revision\", \"ids\", \"summary\", \"status_counts\", \"priority_distribution\", \"projects\", \"query\"]

        def compare_reports(first, second):
            return {\"revision_delta\": second[\"revision\"] - first[\"revision\"], \"count_delta\": second[\"summary\"][\"count\"] - first[\"summary\"][\"count\"], \"estimate_delta\": round(second[\"summary\"][\"estimate\"] - first[\"summary\"][\"estimate\"], 6)}
    """,
    "dispatchboard/service.py": """
        from .audit import audit_event
        from .codec import decode_bundle, encode_bundle
        from .common import clone
        from .events import EventLog
        from .model import Project, Ticket, User
        from .policy import paginate
        from .query import TicketQuery
        from .report import make_report, render_text
        from .repository import TicketRepository

        class WorkspaceService:
            def __init__(self, records, projects, users):
                self.repository = TicketRepository(records, [Project.from_record(x) for x in projects], [User.from_record(x) for x in users])
                self.events = EventLog()

            @property
            def revision(self):
                return self.repository.revision

            def list_tickets(self, *, status=None, owner=None, project=None, labels=(), text=None, limit=100, offset=0):
                query = TicketQuery.create(status=status, owner=owner, project=project, labels=labels, text=text)
                return paginate(self.repository.find(query), limit, offset)

            def get_ticket(self, identifier):
                return self.repository.get(identifier)

            def summary(self, **filters):
                query = TicketQuery.create(**filters)
                from .metrics import summarize
                return summarize(self.repository.find(query))

            def report(self, **filters):
                query = TicketQuery.create(**filters)
                return make_report(self.repository.find(query), revision=self.revision, query=query.as_mapping())

            def add_ticket(self, record, actor=\"system\"):
                before = self.repository.all(); revision = self.repository.add(record, actor); after = self.repository.all(); self.events.append(\"ticket.added\", revision, actor, audit_event(before, after, revision, \"add\")); return self.get_ticket(record[\"id\"])

            def update_ticket(self, identifier, changes, actor=\"system\"):
                before = self.repository.all(); revision = self.repository.update(identifier, changes, actor); after = self.repository.all(); self.events.append(\"ticket.updated\", revision, actor, audit_event(before, after, revision, \"update\")); return self.get_ticket(identifier)

            def remove_ticket(self, identifier, actor=\"system\"):
                before = self.repository.all(); revision = self.repository.remove(identifier, actor); after = self.repository.all(); self.events.append(\"ticket.removed\", revision, actor, audit_event(before, after, revision, \"remove\")); return revision

            def export_workspace(self):
                bundle = self.repository.bundle(); return encode_bundle(self.repository.users, self.repository.projects, self.repository.all(), bundle[\"history\"])

            def import_workspace(self, payload):
                bundle = decode_bundle(payload); self.repository.replace_bundle(bundle); self.events.restore([]); return self.revision

            def project_keys(self):
                return self.repository.project_keys()

            def owner_keys(self):
                return self.repository.owner_keys()

            def event_records(self):
                return [event.as_record() for event in self.events.all()]

            def text_report(self, **filters):
                return render_text(self.report(**filters))
    """,
    "dispatchboard/api.py": """
        from .service import WorkspaceService

        class WorkspaceAPI:
            def __init__(self, service: WorkspaceService):
                self.service = service

            def tickets(self, status=None, owner=None, project=None, labels=(), text=None, limit=100, offset=0):
                return self.service.list_tickets(status=status, owner=owner, project=project, labels=labels, text=text, limit=limit, offset=offset)

            def ticket(self, identifier):
                return self.service.get_ticket(identifier)

            def summary(self, **filters):
                return self.service.summary(**filters)

            def report(self, **filters):
                return self.service.report(**filters)

            def add(self, record, actor=\"system\"):
                return self.service.add_ticket(record, actor)

            def update(self, identifier, changes, actor=\"system\"):
                return self.service.update_ticket(identifier, changes, actor)

            def remove(self, identifier, actor=\"system\"):
                return self.service.remove_ticket(identifier, actor)

            def export(self):
                return self.service.export_workspace()

            def import_data(self, payload):
                return self.service.import_workspace(payload)

            def projects(self):
                return self.service.project_keys()

            def owners(self):
                return self.service.owner_keys()

            def events(self):
                return self.service.event_records()

            def text_report(self, **filters):
                return self.service.text_report(**filters)
    """,
}


def _records(seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    shift = int(seed) % 7
    users = [
        {"key": "alice", "display_name": "Alice North", "role": "admin"},
        {"key": "bob", "display_name": "Bob South", "role": "lead"},
        {"key": "cara", "display_name": "Cara East", "role": "member"},
        {"key": "devon", "display_name": "Devon West", "role": "member"},
    ]
    projects = [
        {"key": "atlas", "name": "Atlas migration", "owner": "alice", "labels": ["core", "platform"]},
        {"key": "beacon", "name": "Beacon reliability", "owner": "bob", "labels": ["operations", "reliability"]},
        {"key": "cinder", "name": "Cinder research", "owner": "cara", "labels": ["research", "data"]},
        {"key": "delta", "name": "Delta release", "owner": "devon", "labels": ["release", "platform"]},
    ]
    statuses = ["open", "blocked", "closed"]
    owners = ["alice", "bob", "cara", "devon"]
    labels = [["core", "urgent"], ["ops"], ["research", "fractional"], ["release", "platform"], ["core", "data"], ["ops", "urgent"]]
    tickets = []
    for index in range(18):
        tickets.append({"id": 100 + shift + index * 3, "project": projects[index % len(projects)]["key"], "title": ["Repair ingestion queue", "Review service contract", "Verify fractional metrics", "Prepare release notes", "Investigate stale worker", "Document recovery path"][index % 6], "status": statuses[index % len(statuses)], "owner": owners[index % len(owners)], "priority": (index % 5) + 1, "estimate": [1.25, 2.5, 3.75, 5.5, 0.875, 4.125][index % 6], "labels": labels[index % len(labels)], "created_day": 10 + index * 2})
    return users, projects, tickets


OLD_TESTS = """
    import json
    import unittest
    from dispatchboard.api import WorkspaceAPI
    from dispatchboard.service import WorkspaceService

    DATA = json.loads(open(\"data/workspace.json\").read())

    class OldContract(unittest.TestCase):
        def make(self):
            return WorkspaceService(DATA[\"tickets\"], DATA[\"projects\"], DATA[\"users\"])

        def test_listing_and_normalized_filters(self):
            service = self.make(); api = WorkspaceAPI(service)
            self.assertEqual(len(api.tickets()), 18)
            self.assertEqual([item.identifier for item in api.tickets(status=\" OPEN \")], [item.identifier for item in api.tickets(status=\"open\")])
            self.assertTrue(all(item.owner == \"alice\" for item in api.tickets(owner=\" Alice \") ))
            self.assertTrue(all(\"urgent\" in item.labels for item in api.tickets(labels=[\" urgent \" ])))

        def test_fractional_summary_and_report_contract(self):
            service = self.make(); report = service.report()
            self.assertEqual(report[\"summary\"][\"count\"], 18)
            self.assertGreater(report[\"summary\"][\"estimate\"], 0)
            self.assertEqual(report[\"ids\"], [item.identifier for item in service.list_tickets()])
            self.assertIn(\"status_counts\", report)

        def test_mutation_revision_and_events(self):
            service = self.make(); first = service.revision
            target = service.list_tickets()[0]
            service.update_ticket(target.identifier, {\"status\": \"closed\", \"estimate\": 6.25}, actor=\"alice\")
            self.assertEqual(service.revision, first + 1)
            self.assertEqual(service.get_ticket(target.identifier).status, \"closed\")
            self.assertEqual(len(service.event_records()), 1)

        def test_round_trip_old_workspace(self):
            service = self.make(); payload = service.export_workspace(); restored = self.make()
            restored.import_workspace(payload)
            self.assertEqual(restored.report(), service.report())

    if __name__ == \"__main__\": unittest.main()
"""


def _verifier_script() -> str:
    return _dedent("""
        #!/usr/bin/env python3
        import json
        from pathlib import Path
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from verifier.contract import checks
        result = checks(Path(__file__).resolve().parents[1])
        print(json.dumps({"checks": [item["passed"] for item in result], "details": result}, sort_keys=True))
        sys.exit(0 if len(result) == 8 else 2)
    """)


CONTRACT = _dedent("""
    import json
    from dispatchboard.api import WorkspaceAPI
    from dispatchboard.service import WorkspaceService

    def _safe(name, function):
        try:
            return {"name": name, "passed": bool(function()), "detail": ""}
        except Exception as exc:
            return {"name": name, "passed": False, "detail": type(exc).__name__}

    def _data(root):
        return json.loads((root / "data/workspace.json").read_text())

    def _service(root):
        data = _data(root)
        return WorkspaceService(data["tickets"], data["projects"], data["users"])

    def checks(root):
        def c1():
            service = _service(root); api = WorkspaceAPI(service)
            item = api.create_bookmark("alice", "urgent work", {"status": " open ", "labels": [" urgent "]})
            return item["name"] == "urgent work" and [ticket.identifier for ticket in api.run_bookmark("alice", "urgent work")] == [ticket.identifier for ticket in api.tickets(status="open", labels=["urgent"])]

        def c2():
            service = _service(root); api = WorkspaceAPI(service)
            api.create_bookmark("alice", "active", {"status": "open"}); before = [x.identifier for x in api.run_bookmark("alice", "active")]
            target = api.tickets(status="open")[0]; api.update(target.identifier, {"status": "closed"}, actor="alice")
            after = [x.identifier for x in api.run_bookmark("alice", "active")]
            return target.identifier in before and target.identifier not in after and before != after

        def c3():
            service = _service(root); api = WorkspaceAPI(service)
            api.create_bookmark("alice", "mine", {"owner": "alice"}); api.create_bookmark("bob", "mine", {"owner": "bob"})
            return api.list_bookmarks("alice") == ["mine"] and api.list_bookmarks("bob") == ["mine"] and all(item.owner == "alice" for item in api.run_bookmark("alice", "mine"))

        def c4():
            service = _service(root); api = WorkspaceAPI(service)
            api.create_bookmark("alice", "one", {"project": "atlas"}); api.create_bookmark("alice", "two", {"project": "beacon", "labels": ["urgent"]})
            try: api.create_bookmark("alice", "one", {"status": "closed"})
            except Exception: collision = True
            else: collision = False
            return collision and api.list_bookmarks("alice") == ["one", "two"]

        def c5():
            service = _service(root); api = WorkspaceAPI(service)
            api.create_bookmark("alice", "portable", {"project": "cinder", "text": "fractional"}); payload = api.export_bookmarks("alice")
            other = _service(root); other_api = WorkspaceAPI(other); other_api.import_bookmarks("cara", payload)
            return other_api.list_bookmarks("cara") == ["portable"] and [x.identifier for x in other_api.run_bookmark("cara", "portable")] == [x.identifier for x in api.run_bookmark("alice", "portable")]

        def c6():
            service = _service(root); api = WorkspaceAPI(service)
            api.create_bookmark("alice", "report", {"project": "atlas"}); report = api.bookmark_report("alice", "report")
            return report["bookmark"] == "report" and report["owner"] == "alice" and report["query"]["project"] == "atlas" and report["summary"]["count"] == len(api.run_bookmark("alice", "report"))

        def c7():
            service = _service(root); api = WorkspaceAPI(service)
            api.create_bookmark("alice", "compound", {"status": "opened", "owner": " ALICE ", "labels": [" URGENT ", "core"], "text": "REPAIR"})
            result = api.run_bookmark("alice", "compound")
            return all(item.status == "open" and item.owner == "alice" and {"urgent", "core"}.issubset(item.labels) and "repair" in item.title.casefold() for item in result)

        def c8():
            service = _service(root); api = WorkspaceAPI(service)
            api.create_bookmark("alice", "remove", {"status": "blocked"}); present = api.list_bookmarks("alice"); api.delete_bookmark("alice", "remove")
            return present == ["remove"] and api.list_bookmarks("alice") == [] and api.report()["summary"]["count"] == len(api.tickets())

        return [_safe(name, function) for name, function in zip(
            ["bookmark creation", "dynamic bookmark execution", "owner isolation", "bookmark lifecycle", "bookmark portability", "bookmark reporting", "compound query behavior", "delete and old API compatibility"],
            [c1, c2, c3, c4, c5, c6, c7, c8],
        )]
""")


def make_instance(family: str, seed: int) -> TaskInstance:
    if family != "P1_named_report_bookmarks":
        raise ValueError(f"unknown V2.4 family: {family}")
    users, projects, tickets = _records(seed)
    files = {name: _dedent(source) for name, source in BASE_FILES.items()}
    files["data/workspace.json"] = json.dumps({"users": users, "projects": projects, "tickets": tickets}, indent=2, sort_keys=True)
    files["tests/test_old_contract.py"] = _dedent(OLD_TESTS)
    scope = {"editable": ["dispatchboard/**/*.py"], "immutable": ["README.md", "tests/**", "verifier/**", "data/**", ".ekalavya/**"], "generated_ignored": [".pytest_cache/**", "__pycache__/**", "*.pyc"]}
    specification = {
        "suite": SUITE_NAME, "version": SUITE_VERSION, "family": family, "seed": seed,
        "requirements": [
            "add owner-scoped named report bookmarks without changing the existing ticket API",
            "normalize and persist compound ticket query criteria",
            "execute a bookmark against current data after later mutations",
            "support independent names, deletion, export/import, and report metadata",
        ],
        "checks": ["bookmark creation", "dynamic bookmark execution", "owner isolation", "bookmark lifecycle", "bookmark portability", "bookmark reporting", "compound query behavior", "delete and old API compatibility"],
        "evaluation_contract": "Eight independently executed public behavioral checks; old-contract tests must remain green.",
    }
    files["README.md"] = _dedent("""
        # Dispatchboard feature request

        The existing ticket workspace is correct and covered by
        `tests/test_old_contract.py`. Add owner-scoped named report bookmarks.

        A bookmark stores a named, reusable report query for one owner. It must
        accept the existing query dimensions (status, owner, project, labels,
        and title text), normalize equivalent user input, and run against the
        current ticket data each time it is used. Later ticket changes must be
        reflected without changing the old ticket API.

        Owners may use the same bookmark name independently. Duplicate names
        for one owner must be rejected; bookmarks can be listed and deleted.
        Bookmarks must be exportable and importable for another owner while
        preserving normalized criteria. Reports generated from a bookmark must
        retain ordinary report summaries and identify the bookmark and owner.

        Preserve old behavior, fractional estimates, revisions, events,
        workspace round-trips, and compatibility of all existing methods.
        Run the old tests and `python verifier/verify.py`. Do not edit tests,
        verifier files, task metadata, or fixture data.
    """)
    files["verifier/contract.py"] = CONTRACT
    files["verifier/verify.py"] = _verifier_script()
    files[".ekalavya/edit-scope.json"] = json.dumps(scope, indent=2, sort_keys=True)
    files[".ekalavya/task.json"] = json.dumps({"suite": SUITE_NAME, "version": SUITE_VERSION, "family": family, "seed": seed}, indent=2, sort_keys=True)
    prompt = "Implement the named report bookmark feature described in README.md while preserving the complete existing ticket workspace contract. Use the public verifier to check behavior; do not modify tests, verifier files, metadata, or fixture data."
    return TaskInstance(family, seed, prompt, files, specification, scope, files["verifier/verify.py"])


def materialize(instance: TaskInstance, workspace: Path) -> Path:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for name, value in instance.files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    return workspace


def workspace_digest(workspace: Path) -> str:
    digest = hashlib.sha256()
    paths = (path for path in workspace.rglob("*") if path.is_file() and path.suffix not in IGNORED_GENERATED_SUFFIXES and not any(part in IGNORED_GENERATED_DIRS for part in path.parts))
    for path in sorted(paths):
        digest.update(path.relative_to(workspace).as_posix().encode()); digest.update(b"\0"); digest.update(path.read_bytes())
    return digest.hexdigest()
