"""Public, versioned harness capability and eligibility catalogue."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

EXECUTION_CLASSES = ("ordinary", "public_characterization", "hidden_benchmark")
CAPABILITIES = (
    "exact_model_selection", "reasoning_selection", "writable_workspace",
    "filesystem_containment", "tool_network_containment",
    "provider_transport_available", "telemetry", "tool_trace",
    "token_usage", "cost_usage",
)
STATUSES = {"supported", "unsupported", "unverified", "version_limited", "unavailable"}
REQUEST_METRIC_SEMANTICS = {"provider_model_request", "harness_session", "unavailable"}
TOOL_EVENT_TELEMETRY = {"complete", "partial", "unavailable"}
TOKEN_METRIC_SEMANTICS = {"provider_billing_tokens", "harness_reported_usage", "unavailable"}


@dataclass(frozen=True)
class HarnessRecord:
    name: str
    version: str
    command: str
    transport: str
    eligibility: dict[str, str]
    capabilities: dict[str, str]
    reason: str
    evidence_label: str
    exact_model_scope: str
    request_metric_semantics: str
    tool_event_telemetry: str
    token_metric_semantics: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "transport": self.transport,
            "eligibility": dict(self.eligibility),
            "capabilities": dict(self.capabilities),
            "reason": self.reason,
            "evidence": self.evidence_label,
            "exact_model_scope": self.exact_model_scope,
            "telemetry": {
                "request_metric_semantics": self.request_metric_semantics,
                "tool_event_telemetry": self.tool_event_telemetry,
                "token_metric_semantics": self.token_metric_semantics,
            },
        }


def audited_registry() -> tuple[HarnessRecord, ...]:
    common_agy = {key: "supported" for key in CAPABILITIES}
    common_agy.update({"filesystem_containment": "unsupported", "tool_network_containment": "unsupported", "tool_trace": "unavailable", "cost_usage": "unavailable"})
    return (
        HarnessRecord(
            "agy", "1.1.26", "agy", "agy",
            {"ordinary": "supported", "public_characterization": "supported", "hidden_benchmark": "unsupported"},
            common_agy,
            "AGY 1.1.26 exposes no supported independent candidate-tool subprocess boundary; native sandbox does not establish parent/network containment",
            "AGY 1.1.26 help and changelog audit; prior isolation probe",
            "Gemini Flash exact runtime IDs and reasoning variants",
            "harness_session", "unavailable", "harness_reported_usage",
        ),
        HarnessRecord(
            "opencode", "1.17.2", "opencode", "opencode",
            {"ordinary": "unverified", "public_characterization": "unsupported", "hidden_benchmark": "unsupported"},
            {key: "unverified" for key in CAPABILITIES} | {"exact_model_selection": "unsupported", "provider_transport_available": "supported"},
            "installed model catalogue did not expose an exact Gemini characterization candidate; isolation contract unverified",
            "zero-inference OpenCode model/help inspection",
            "no exact Gemini 3.7/3.8 model observed",
            "unavailable", "unavailable", "unavailable",
        ),
        HarnessRecord(
            "gemini-cli", "0.55.1", "gemini", "gemini-cli",
            {"ordinary": "unverified", "public_characterization": "unverified", "hidden_benchmark": "unsupported"},
            {key: "unverified" for key in CAPABILITIES} | {"filesystem_containment": "version_limited", "tool_network_containment": "version_limited", "provider_transport_available": "supported"},
            "Linux sandbox requires unavailable Docker or Podman; exact Gemini generation exposure not established",
            "installed Gemini CLI sandbox documentation and version inspection",
            "exact model availability unverified",
            "unavailable", "unavailable", "unavailable",
        ),
    )


def _version(command: str, fallback: str) -> str:
    if not shutil.which(command):
        return fallback
    try:
        result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return fallback
    return (result.stdout or result.stderr).strip() or fallback


def current_registry() -> list[dict[str, Any]]:
    """Return public-safe registry data with current command availability."""
    result = []
    for record in audited_registry():
        item = record.as_dict()
        item["installed"] = bool(shutil.which(record.command))
        item["observed_version"] = _version(record.command, record.version) if item["installed"] else None
        result.append(item)
    return result


def validate_registry(records: list[dict[str, Any]]) -> None:
    for record in records:
        if set(record.get("eligibility", {})) != set(EXECUTION_CLASSES):
            raise ValueError(f"harness eligibility must cover {EXECUTION_CLASSES}: {record.get('name')}")
        invalid = (set(record.get("eligibility", {}).values()) | set(record.get("capabilities", {}).values())) - STATUSES
        if invalid:
            raise ValueError(f"invalid harness registry status values: {sorted(invalid)}")
        telemetry = record.get("telemetry", {})
        if telemetry.get("request_metric_semantics") not in REQUEST_METRIC_SEMANTICS:
            raise ValueError(f"invalid request metric semantics: {record.get('name')}")
        if telemetry.get("tool_event_telemetry") not in TOOL_EVENT_TELEMETRY:
            raise ValueError(f"invalid tool event telemetry: {record.get('name')}")
        if telemetry.get("token_metric_semantics") not in TOKEN_METRIC_SEMANTICS:
            raise ValueError(f"invalid token metric semantics: {record.get('name')}")
