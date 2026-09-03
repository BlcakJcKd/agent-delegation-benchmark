"""Synthetic scientific reasoning cases and deterministic, non-verbosity rubrics."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReasoningCase:
    case_id: str
    prompt: str
    rubric: tuple[str, ...]


CASES = (
    ReasoningCase("R1_seed_instability", """A model is evaluated on seeds S1-S5. Relative improvement over baseline is: S1 +1%, S2 +2%, S3 +0%, S4 +1%, S5 +38%. The pooled mean improvement is 8.4%. Identify the methodological concern, strongest justified conclusion, appropriate paired analysis, and one discriminating follow-up.""", ("identifies outlier-driven instability", "calibrates conclusion", "recommends paired per-seed analysis", "proposes follow-up sensitivity/bootstrap/extra seeds")),
    ReasoningCase("R2_controller_comparison", """Controller A is evaluated on stochastic scenarios {1,2,3,4,5}; controller B is evaluated on {1,2,3,4,6}, and scenario 6 is easier. A mean reward is 80 and B mean reward is 84. Identify the flaw, explain why means are insufficient, specify a corrected experiment, and state what claim remains supportable.""", ("identifies non-identical scenarios", "explains confounding", "requires matched paired random seeds/scenarios", "limits claim to this non-comparable observation")),
    ReasoningCase("R3_metric_fidelity", """Model A has RMSE 0.10 and visibly misses peaks and cycle timing. Model B has RMSE 0.12 but tracks peaks, phase, and state transitions. Explain what RMSE establishes, what it cannot establish, which diagnostics matter, and how to word the comparison.""", ("distinguishes pointwise error from dynamics", "avoids declaring A universally better", "requests cycle/phase/peak/state diagnostics", "gives calibrated trade-off wording")),
)


def score(case_id: str, answer: str) -> dict[str, object]:
    text = answer.lower()
    terms = {
        "R1_seed_instability": (("outlier" in text or "unstable" in text) and ("paired" in text or "per-seed" in text), ("conclu" in text or "cannot" in text or "not enough" in text), ("bootstrap" in text or "sensitivity" in text or "additional seed" in text or "follow-up" in text)),
        "R2_controller_comparison": (("scenario 6" in text or "non-ident" in text or "unfair" in text), ("paired" in text or "matched" in text), ("confound" in text or "mean" in text and "insufficient" in text), ("claim" in text or "conclu" in text)),
        "R3_metric_fidelity": (("rmse" in text and ("dynamic" in text or "cycle" in text or "phase" in text)), ("peak" in text or "transition" in text), ("cannot" in text or "does not" in text or "not establish" in text), ("word" in text or "claim" in text or "trade-off" in text)),
    }
    checks = terms.get(case_id, ())
    return {"case": case_id, "score": sum(bool(x) for x in checks), "maximum": len(checks), "checks": list(map(bool, checks))}

