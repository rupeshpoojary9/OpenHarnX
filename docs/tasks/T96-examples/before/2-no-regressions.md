# OpenHarnX report: NO REGRESSIONS

- Contract: Locked suite at c8cceac4665e (urn:ohx:rev:2f2cf643-57d7-4416-81a9-7a6236c90d1d)
- Candidate: `sha256:c7c048d6a4293910d326f20995cbeb63b79c7bf1b350ce795da41e62689f03a6` (base commit c8cceac4665ee17c3f50578f3da738e9d4dbe5bc)
- Gate: **pass**, evidence coverage 100%
- Verifier protection: none: checkers ran without isolation, so tampering is detected, not prevented

## What this verdict supports

- No regressions: yes, every test that passed before still passes
- Tests: 1 of 1 tests checked this change
- Acceptance criteria: none: no acceptance tests were agreed, so this does not show that the task is done; add them with `ohx contract new --acceptance`

## Obligations

| Obligation | Mandatory | Status | Reasons |
|---|---|---|---|
| locked-tests | no | pass | none |
| tests | no | pass | none |
| weakening | yes | pass | none |
| no-new-failures-locked-tests | yes | pass | none |
| no-new-failures-tests | yes | pass | none |

## Cost

- Agent work: unknown: no agent run recorded
- OpenHarnX overhead: 0 model calls, verifier time 410 ms

## Changelog entry

- The test suite of the working tree at c8cceac4665e, locked

## Limitations

- 0 ignored file(s) present and not in the candidate identity

This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.
