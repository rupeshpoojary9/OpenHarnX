# OpenHarnX report: BLOCKED

- Contract: Fix half (urn:ohx:rev:d348900a-906e-48ea-949f-b4e7ff06c643)
- Candidate: `sha256:19e498e4b540ca52c2db1682c0b2abab548920327c1363ed61a50e7ae40189d0` (base commit 4f38ed0230fc4d419e90ea4002a8d8d5af6d34ba)
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
- OpenHarnX overhead: 0 model calls, verifier time 1323 ms

## Changelog entry

- half() returns half of its argument

## Limitations

- 0 ignored file(s) present and not in the candidate identity

This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.
