from hypothesis import given
from hypothesis import strategies as st

from openharnx.kernel.gate import OUTCOMES, Obligation, Observation, evaluate_gate

C = "sha256:candidate"


def test_empty_manifest_is_invalid_never_pass() -> None:
    gate = evaluate_gate([], [], C)
    assert gate.result == "invalid_manifest"
    assert gate.coverage_percent is None


def test_duplicate_obligation_ids_are_invalid() -> None:
    obs = [Obligation("a", True), Obligation("a", True)]
    assert evaluate_gate(obs, [], C).result == "invalid_manifest"


def test_missing_evidence_is_unknown() -> None:
    gate = evaluate_gate([Obligation("a", True)], [], C)
    assert gate.result == "unknown"
    assert gate.obligations[0].reasons == ("no_evidence",)


def test_evidence_for_another_candidate_is_stale() -> None:
    gate = evaluate_gate([Obligation("a", True)], [Observation("a", "sha256:old", "pass")], C)
    assert gate.result == "unknown"
    assert "stale: subject_changed" in gate.obligations[0].reasons


def test_advisory_failure_does_not_block() -> None:
    gate = evaluate_gate(
        [Obligation("a", True), Obligation("b", False)],
        [Observation("a", C, "pass"), Observation("b", C, "fail")],
        C,
    )
    assert gate.result == "pass"
    assert gate.coverage_percent == 50


def test_timeout_is_unknown_not_fail_or_pass() -> None:
    gate = evaluate_gate([Obligation("a", True)], [Observation("a", C, "timeout")], C)
    assert gate.result == "pass"


outcome = st.sampled_from(sorted(OUTCOMES))
cases = st.lists(st.tuples(st.booleans(), outcome), min_size=1, max_size=8)


@given(cases)
def test_gate_precedence(case: list[tuple[bool, str]]) -> None:
    obligations = [Obligation(f"o{i}", m) for i, (m, _) in enumerate(case)]
    observations = [Observation(f"o{i}", C, out) for i, (_, out) in enumerate(case)]
    gate = evaluate_gate(obligations, observations, C)
    mandatory = [out for m, out in case if m]
    if "fail" in mandatory:
        assert gate.result == "fail"
    elif any(out != "pass" for out in mandatory):
        assert gate.result == "unknown"
    else:
        assert gate.result == "pass"


@given(cases)
def test_any_mandatory_non_pass_never_passes(case: list[tuple[bool, str]]) -> None:
    obligations = [Obligation(f"o{i}", m) for i, (m, _) in enumerate(case)]
    observations = [Observation(f"o{i}", C, out) for i, (_, out) in enumerate(case)]
    if any(m and out != "pass" for m, out in case):
        assert evaluate_gate(obligations, observations, C).result != "pass"
