"""Named, practical operating tiers for controlled benchmark runs.

The tiers intentionally match practical operating roles, not provider compute.
They are the only configurations eligible for controlled aggregate analysis.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    id: str
    purpose: str
    models: dict[str, str]
    codex_reasoning_effort: str
    claude_reasoning_effort: str
    agy_reasoning_note: str

    def metadata(self) -> dict[str, object]:
        return {
            "id": self.id,
            "methodology": "matched practical operating tiers",
            "purpose": self.purpose,
            "models": self.models,
            "requested_reasoning_effort": {
                "codex": self.codex_reasoning_effort,
                "claude": self.claude_reasoning_effort,
                "agy": self.agy_reasoning_note,
            },
        }


TIERS: dict[str, Tier] = {
    "tier-a-medium": Tier(
        id="tier-a-medium",
        purpose="Everyday medium-capability coding and research delegation.",
        models={
            "codex": "gpt-5.6-terra",
            "claude": "claude-sonnet-5",
            "agy": "gemini-3.1-pro-low",
        },
        codex_reasoning_effort="medium",
        claude_reasoning_effort="medium",
        agy_reasoning_note="encoded by selected model variant: Gemini 3.1 Pro (Low)",
    ),
    "tier-b-cheap": Tier(
        id="tier-b-cheap",
        purpose="Cheap, high-throughput routine delegated work.",
        models={
            "codex": "gpt-5.6-luna",
            "claude": "claude-haiku-4-5-20251001",
            "agy": "gemini-3.7-flash-medium",
        },
        codex_reasoning_effort="medium",
        claude_reasoning_effort="medium",
        agy_reasoning_note="encoded by selected model variant: Gemini 3.7 Flash (Medium)",
    ),
}


PILOT_RUN_LABELS: frozenset[str] = frozenset({
    "first-comparison",
    "first-valid-comparison",
    "first-valid-codex-repair",
    "first-valid-codex-terra",
})


def tier_by_id(tier_id: str) -> Tier:
    return TIERS[tier_id]
