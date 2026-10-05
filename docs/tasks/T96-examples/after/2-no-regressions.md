# OpenHarnX report: NO REGRESSIONS

## Requested outcome

**Locked suite at 67b843e746ad** (suite): The test suite of the working tree at 67b843e746ad, locked

Stated in contract revision `urn:ohx:rev:0619ceaa-14a8-47c8-92ae-89082e214748`, accepted by Dev <dev@example.com>. No acceptance tests were agreed, so no check looks for it.

## What changed

Observed: 1 file(s) differ, by content digest, from the files accepted with the contract (base commit `67b843e746ad`). Why each changed is not recorded; an agent's own account of its change is not evidence.

| File | Change | Kind | Imported by a test run |
|---|---|---|---|
| `calc.py` | modified | code | yes |

Diff: `git diff 67b843e746ad`, which also shows edits made before the contract was accepted (such as the acceptance tests).

## What was verified

- `no-new-failures-locked-tests` (built-in, mandatory): every test in `locked-tests` that passed before passes ([output](evidence/no-new-failures-locked-tests.txt))
- `no-new-failures-tests` (built-in, mandatory): every test in `tests` that passed before passes ([output](evidence/no-new-failures-tests.txt))
- `weakening` (built-in, mandatory): no removed test or assertion, new skip, new suppression or loosened check configuration was found ([output](evidence/weakening.txt))
- `locked-tests` (regression, advisory): passed ([output](evidence/locked-tests.txt))
- `tests` (regression, advisory): passed ([output](evidence/tests.txt))
- Note: a passing check does not show that every changed line ran, and a requirement with a passing test is not thereby fully tested. The mutation check, where it ran, is the only measure here of how much the tests notice.

Each output link is a copy of the check's recorded output; report.json gives its digest and evidence record.

## What remains unverified

- Whether the requested outcome is done: no acceptance tests were agreed, so no check looked for it
- Isolation of the checks: none: checkers ran without isolation, so tampering is detected, not prevented

## Decisions for you

1. Is the requested outcome done? No agreed test checks it. Judge it from the diff, or agree acceptance tests with `ohx contract new --acceptance`.
2. The checks ran without the sandbox, so code under test could have changed what they saw. Rely on the result only as far as you trust that code.

## Details

- Contract: Locked suite at 67b843e746ad (urn:ohx:rev:0619ceaa-14a8-47c8-92ae-89082e214748)
- Candidate: `sha256:3258fc915f7b7a80f46a5fc483cd1a0ab70ea27dedd783cb57bd6d2aca52b54a` (base commit 67b843e746ad7846e9dae68f09fd22b05bb4bcfd)
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
- OpenHarnX overhead: 0 model calls, verifier time 386 ms

## Changelog entry

- The test suite of the working tree at 67b843e746ad, locked

## Limitations


This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.
