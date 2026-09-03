"""Explicit profile resolution; never auto-fails over or shops providers."""

from __future__ import annotations

from typing import Any

from .schema import CandidateIdentity, ReasoningPolicy, Resolution, RunIntent

SAME_PROVIDER_NATIVE = {
    "codex": "same-provider-native-required",
    "claude": "same-provider-native-required",
    "gemini": "same-provider-native-required",
}


def resolve(intent: RunIntent, profile: dict[str, Any], candidates: list[dict[str, Any]]) -> Resolution:
    permitted = set(profile.get("permitted_candidates") or [])
    default_key = profile.get("default_identity_key")
    eligible = [c for c in candidates if c.get("lifecycle") in {"current", "previous", "candidate"} and (not permitted or c.get("identity_key") in permitted)]
    filters = {"provider": intent.provider, "family": intent.family, "provider_model_id": intent.model}
    filtered = [c for c in eligible if all(v is None or c.get(k) == v for k, v in filters.items())]
    alternatives = tuple({"identity_key": c.get("identity_key"), "provider": c.get("provider"), "family": c.get("family"), "provider_model_id": c.get("provider_model_id"), "lifecycle": c.get("lifecycle")} for c in eligible)
    explicit_candidate = bool(intent.model)
    if default_key and not any(c.get("identity_key") == default_key for c in filtered):
        if not filtered:
            return Resolution(intent, None, reason="configured profile default does not satisfy requested constraints", state="unavailable", alternatives=alternatives)
    chosen = next((c for c in filtered if c.get("identity_key") == default_key), None) if default_key else (filtered[0] if len(filtered) == 1 else None)
    if chosen is None and explicit_candidate and len(filtered) == 1:
        chosen = filtered[0]
    if chosen is None:
        return Resolution(intent, None, reason="profile has no unambiguous configured candidate; choose one explicitly", state="unavailable", alternatives=alternatives)
    primary = (intent.primary or "").strip().lower()
    aliases = {"codex-cli": "codex", "claude-code": "claude", "antigravity": "gemini", "agy": "gemini"}
    primary = aliases.get(primary, primary)
    if primary and primary == chosen.get("provider") and primary in SAME_PROVIDER_NATIVE:
        return Resolution(intent, None, reason=f"primary provider {primary} must use its native agent capability", state="same-provider-native-required", alternatives=alternatives)
    caps = chosen.get("capabilities") or {}
    policy = ReasoningPolicy(mode=profile.get("reasoning_policy", "overrideable"), default=intent.reasoning if intent.reasoning is not None else profile.get("default_reasoning"), supported=tuple(caps.get("reasoning_values") or ()))
    try:
        reasoning = policy.validate(intent.reasoning)
    except ValueError as exc:
        return Resolution(intent, None, reason=str(exc), state="invalid-reasoning", alternatives=alternatives)
    supported_harnesses = tuple(caps.get("harness_values") or ())
    if not supported_harnesses:
        supported_harnesses = tuple(value for value in (chosen.get("harness"), chosen.get("serving_engine"), chosen.get("transport")) if value)
    if intent.harness and intent.harness not in supported_harnesses:
        return Resolution(intent, None, reason=f"unsupported harness {intent.harness!r}; supported: {list(supported_harnesses)!r}", state="invalid-harness", alternatives=alternatives)
    candidate = CandidateIdentity(**{k: chosen.get(k) for k in CandidateIdentity.__dataclass_fields__})
    return Resolution(intent, candidate, reasoning, intent.harness or profile.get("harness") or chosen.get("harness") or chosen.get("serving_engine") or chosen.get("transport"), chosen.get("harness_version") or chosen.get("serving_engine_version"), chosen.get("transport"), chosen.get("legacy_route"), "configured profile default" if default_key else "explicit sole candidate", "resolved", alternatives)
