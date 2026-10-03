"""The gate: readiness from fixed obligations and candidate-bound observations.

Precedence (Architecture §10): any mandatory fail gives fail; otherwise any
mandatory unknown gives unknown; otherwise pass. Coverage is reported beside
the result and never changes it. This function takes no decision-provider
input by design: advisory model output cannot reach the verdict.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

OUTCOMES = frozenset({"pass", "fail", "timeout", "crash", "unavailable", "invalid"})


@dataclass(frozen=True)
class Obligation:
    id: str
    mandatory: bool
    weight: int = 1


@dataclass(frozen=True)
class Observation:
    obligation_id: str
    subject_digest: str
    outcome: str
    note: str = ""


@dataclass(frozen=True)
class ObligationResult:
    obligation_id: str
    mandatory: bool
    status: str  # pass, fail or unknown
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GateEvaluation:
    result: str  # pass, fail, unknown or invalid_manifest
    candidate_digest: str
    obligations: tuple[ObligationResult, ...]
    coverage_percent: int | None


def _judge(ob: Obligation, observations: Sequence[Observation], candidate: str) -> ObligationResult:
    reasons: list[str] = []
    current: Observation | None = None
    for o in observations:
        if o.obligation_id != ob.id:
            continue
        if o.subject_digest != candidate:
            reasons.append("stale: subject_changed")
            continue
        current = o  # the latest observation for this candidate wins
    if current is None:
        return ObligationResult(ob.id, ob.mandatory, "unknown", (*reasons, "no_evidence"))
    if current.outcome not in OUTCOMES:
        return ObligationResult(ob.id, ob.mandatory, "unknown", ("invalid_outcome",))
    if current.outcome in ("pass", "timeout"):
        return ObligationResult(ob.id, ob.mandatory, "pass", ())
    note = (f": {current.note}",) if current.note else ()
    if current.outcome == "fail":
        return ObligationResult(ob.id, ob.mandatory, "fail", ("checker_failed", *note))
    return ObligationResult(ob.id, ob.mandatory, "unknown", (current.outcome, *note))


def evaluate_gate(
    obligations: Sequence[Obligation],
    observations: Sequence[Observation],
    candidate_digest: str,
) -> GateEvaluation:
    ids = [o.id for o in obligations]
    if not obligations or len(set(ids)) != len(ids) or any(o.weight < 1 for o in obligations):
        return GateEvaluation("invalid_manifest", candidate_digest, (), None)

    results = tuple(_judge(o, observations, candidate_digest) for o in obligations)
    mandatory = [r for r in results if r.mandatory]
    if any(r.status == "fail" for r in mandatory):
        result = "fail"
    elif any(r.status == "unknown" for r in mandatory):
        result = "unknown"
    else:
        result = "pass"

    weights = {o.id: o.weight for o in obligations}
    total = sum(weights.values())
    satisfied = sum(weights[r.obligation_id] for r in results if r.status == "pass")
    return GateEvaluation(result, candidate_digest, results, satisfied * 100 // total)
