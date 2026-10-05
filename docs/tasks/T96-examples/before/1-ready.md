# OpenHarnX report: READY

- Contract: Fix half (urn:ohx:rev:8013b459-bdeb-46cb-81dc-c313808b4d9f)
- Candidate: `sha256:741d39af71871003f27b6b36990a6e9cc14c90af4ed09cdba7f59c8988f42b27` (base commit 9f63fadf2a5877590c732e37c7ec3cd0a801be53)
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
- OpenHarnX overhead: 0 model calls, verifier time 1077 ms

## Changelog entry

- half() returns half of its argument

## Limitations

- 0 ignored file(s) present and not in the candidate identity

This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.
