# OpenHarnX report: READY

## Requested outcome

**Fix half** (bugfix): half() returns half of its argument

Stated in contract revision `urn:ohx:rev:1e980714-4623-4337-a04e-4470ce0aed0f`, accepted by Dev <dev@example.com>. It is checked only through the acceptance tests below, not read for meaning.

## What changed

Observed: 1 file(s) differ, by content digest, from the files accepted with the contract (base commit `a295944e34b9`). Why each changed is not recorded; an agent's own account of its change is not evidence.

| File | Change | Kind | Imported by a test run |
|---|---|---|---|
| `calc.py` | modified | code | yes |

Diff: `git diff a295944e34b9`, which also shows edits made before the contract was accepted (such as the acceptance tests).

## What was verified

- `acceptance-test_half` (acceptance, mandatory): passed, 2 of 2 agreed tests: test_half_of_ten, test_half_of_zero ([output](evidence/acceptance-test_half.txt))
- `no-new-failures-locked-tests` (built-in, mandatory): every test in `locked-tests` that passed before passes ([output](evidence/no-new-failures-locked-tests.txt))
- `no-new-failures-tests` (built-in, mandatory): every test in `tests` that passed before passes ([output](evidence/no-new-failures-tests.txt))
- `weakening` (built-in, mandatory): no removed test or assertion, new skip, new suppression or loosened check configuration was found ([output](evidence/weakening.txt))
- `mutation` (built-in, advisory): passed: 2 of 2 mutants of changed lines killed ([output](evidence/mutation.txt))
- `locked-tests` (regression, advisory): passed ([output](evidence/locked-tests.txt))
- `tests` (regression, advisory): passed ([output](evidence/tests.txt))
- Note: a passing check does not show that every changed line ran, and a requirement with a passing test is not thereby fully tested. The mutation check, where it ran, is the only measure here of how much the tests notice.

Each output link is a copy of the check's recorded output; report.json gives its digest and evidence record.

## What remains unverified

- Isolation of the checks: none: checkers ran without isolation, so tampering is detected, not prevented

## Decisions for you

1. The checks ran without the sandbox, so code under test could have changed what they saw. Rely on the result only as far as you trust that code.

## Details

- Contract: Fix half (urn:ohx:rev:1e980714-4623-4337-a04e-4470ce0aed0f)
- Candidate: `sha256:694e3624d39e5b952f7c6d49a7b70d477b6f1e67ee1ad46f98c668568160d20e` (base commit a295944e34b941b702c929b35b90edefa0044ca6)
- Gate: **pass**, evidence coverage 100%
- Verifier protection: none: checkers ran without isolation, so tampering is detected, not prevented

## What this verdict supports

- No regressions: yes, every test that passed before still passes
- Tests: 1 of 1 tests checked this change
- Acceptance criteria: met

## Obligations

| Obligation | Mandatory | Status | Reasons |
|---|---|---|---|
| acceptance-test_half | yes | pass | none |
| locked-tests | no | pass | none |
| tests | no | pass | none |
| weakening | yes | pass | none |
| mutation | no | pass | none |
| no-new-failures-locked-tests | yes | pass | none |
| no-new-failures-tests | yes | pass | none |

## Cost

- Agent work: unknown: no agent run recorded
- OpenHarnX overhead: 0 model calls, verifier time 991 ms

## Changelog entry

- half() returns half of its argument

## Limitations


This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.
