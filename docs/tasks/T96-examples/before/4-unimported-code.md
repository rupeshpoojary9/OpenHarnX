# OpenHarnX report: READY

- Contract: Fix half (urn:ohx:rev:be2097ff-673c-403e-bb8d-0fda5c4b50c7)
- Candidate: `sha256:957c8d7947e5c92a67cdd71a565155f649a8cb8adaaa11e5bc053728c9e6b6a2` (base commit 8206a1f1de2d0c0cb4b5cd9e60241da219cc543b)
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
- OpenHarnX overhead: 0 model calls, verifier time 1315 ms

## Changelog entry

- half() returns half of its argument

## Limitations

- 0 ignored file(s) present and not in the candidate identity

This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.
