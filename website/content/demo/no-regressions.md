# OpenHarnX report: NO REGRESSIONS

## Requested outcome

**Locked suite at 49754aeee83e** (suite): The test suite of the working tree at 49754aeee83e, locked

Stated in contract revision `urn:ohx:rev:4c9a1cd3-990b-4919-bdec-92ac11d7f1ae`, accepted by Shop Owner <owner@example.com>. No acceptance tests were agreed, so no check looks for it.

## What changed

Observed: 2 file(s) differ, by content digest, from the files accepted with the contract (base commit `49754aeee83e`). Why each changed is not recorded; an agent's own account of its change is not evidence.

| File | Change | Kind | Imported by a test run |
|---|---|---|---|
| `pricing.py` | modified | code | yes |
| `tests/test_percent_coupon.py` | added | test |  |

Diff: `git diff 49754aeee83e`, which also shows edits made before the contract was accepted (such as the acceptance tests).

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
- Limitation: Checkers ran with <tmp>/py/bin/python, outside the candidate identity and in no locked environment: its environment (3385 files in /Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12, <tmp>/py/lib/python3.12/site-packages) was fingerprinted at acceptance and matched before the checks ran, so later changes there are caught; changes made before acceptance, compiled __pycache__ files, and code loaded from other folders are not; environment = "uv" in ohx.toml locks it

## Decisions for you

1. Is the requested outcome done? No agreed test checks it. Judge it from the diff, or agree acceptance tests with `ohx contract new --acceptance`.
2. Are the changed tests right? `tests/test_percent_coupon.py` (added). A test written with the change can only confirm what the change does.

## Details

- Contract: Locked suite at 49754aeee83e (urn:ohx:rev:4c9a1cd3-990b-4919-bdec-92ac11d7f1ae)
- Candidate: `sha256:0ef3a4f1c39737a46ed3adec7c181aa65f49db7346293e217c0a488e0c5fabc1` (base commit 49754aeee83ef78db0a5356396dcd0929407d126)
- Gate: **pass**, evidence coverage 100%
- Verifier protection: enforced: checkers ran in the srt sandbox
- Signature: not signed

## What this verdict supports

- No regressions: yes, every test that passed before still passes
- Tests: 5 of 5 tests checked this change
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
- OpenHarnX overhead: 0 model calls, verifier time 498 ms

## Changelog entry

- The test suite of the working tree at 49754aeee83e, locked

## Limitations

- Checkers ran with <tmp>/py/bin/python, outside the candidate identity and in no locked environment: its environment (3385 files in /Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12, <tmp>/py/lib/python3.12/site-packages) was fingerprinted at acceptance and matched before the checks ran, so later changes there are caught; changes made before acceptance, compiled __pycache__ files, and code loaded from other folders are not; environment = "uv" in ohx.toml locks it

This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.

