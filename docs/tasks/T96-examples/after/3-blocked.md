# OpenHarnX report: BLOCKED

## Requested outcome

**Fix half** (bugfix): half() returns half of its argument

Stated in contract revision `urn:ohx:rev:d3971eba-deed-4f78-a043-c38bc92f51aa`, accepted by Dev <dev@example.com>. It is checked only through the acceptance tests below, not read for meaning.

## What changed

Observed: 1 file(s) differ, by content digest, from the files accepted with the contract (base commit `a658d1f6f441`). Why each changed is not recorded; an agent's own account of its change is not evidence.

| File | Change | Kind | Imported by a test run |
|---|---|---|---|
| `calc.py` | modified | code | yes |

Diff: `git diff a658d1f6f441`, which also shows edits made before the contract was accepted (such as the acceptance tests).

## What was verified

- `acceptance-test_half` (acceptance, mandatory): passed, 2 of 2 agreed tests: test_half_of_ten, test_half_of_zero ([output](evidence/acceptance-test_half.txt))
- `weakening` (built-in, mandatory): no removed test or assertion, new skip, new suppression or loosened check configuration was found ([output](evidence/weakening.txt))
- Note: a passing check does not show that every changed line ran, and a requirement with a passing test is not thereby fully tested. The mutation check, where it ran, is the only measure here of how much the tests notice.

Each output link is a copy of the check's recorded output; report.json gives its digest and evidence record.

## What remains unverified

- `no-new-failures-locked-tests` (mandatory): fail: test_calc::test_add passed at acceptance and fails ([output](evidence/no-new-failures-locked-tests.txt))
- `no-new-failures-tests` (mandatory): fail: tests.test_calc::test_add passed at acceptance and fails ([output](evidence/no-new-failures-tests.txt))
- `locked-tests` (advisory): fail: checker_failed ([output](evidence/locked-tests.txt))
- `mutation` (advisory): fail: 1 of 3 mutants of changed lines survived: calc.py:2 `a - b` -> `a + b` ([output](evidence/mutation.txt))
- `tests` (advisory): fail: checker_failed ([output](evidence/tests.txt))
- Isolation of the checks: none: checkers ran without isolation, so tampering is detected, not prevented

## Decisions for you

1. A mandatory check did not pass (`no-new-failures-locked-tests`, `no-new-failures-tests`). Send it back to the agent with the output linked above, or, if the expected behaviour itself is wrong, agree a new contract revision. A report cannot waive a failed check.
2. The checks ran without the sandbox, so code under test could have changed what they saw. Rely on the result only as far as you trust that code.

## Details

- Contract: Fix half (urn:ohx:rev:d3971eba-deed-4f78-a043-c38bc92f51aa)
- Candidate: `sha256:5ab97edd337705cf5ed2107f651046922f33e9e611060e48ed2b495f6d5fb1de` (base commit a658d1f6f44178308377dcaa20266dda0254c3e7)
- Gate: **fail**, evidence coverage 28%
- Verifier protection: none: checkers ran without isolation, so tampering is detected, not prevented

## What this verdict supports

- No regressions: no
- Tests: 0 of 1 tests checked this change
- Acceptance criteria: met

## Obligations

| Obligation | Mandatory | Status | Reasons |
|---|---|---|---|
| locked-tests | no | fail | checker_failed |
| tests | no | fail | checker_failed |
| mutation | no | fail | checker_failed: 1 of 3 mutants of changed lines survived: calc.py:2 `a - b` -> `a + b` |
| no-new-failures-locked-tests | yes | fail | checker_failed: test_calc::test_add passed at acceptance and fails |
| no-new-failures-tests | yes | fail | checker_failed: tests.test_calc::test_add passed at acceptance and fails |
| acceptance-test_half | yes | pass | none |
| weakening | yes | pass | none |

## Cost

- Agent work: unknown: no agent run recorded
- OpenHarnX overhead: 0 model calls, verifier time 1181 ms

## Changelog entry

- half() returns half of its argument

## Limitations


This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.
