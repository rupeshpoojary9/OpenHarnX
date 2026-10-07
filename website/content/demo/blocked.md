# OpenHarnX report: BLOCKED

## Requested outcome

**Locked suite at 49754aeee83e** (suite): The test suite of the working tree at 49754aeee83e, locked

Stated in contract revision `urn:ohx:rev:4c9a1cd3-990b-4919-bdec-92ac11d7f1ae`, accepted by Shop Owner <owner@example.com>. No acceptance tests were agreed, so no check looks for it.

## What changed

Observed: 2 file(s) differ, by content digest, from the files accepted with the contract (base commit `49754aeee83e`). Why each changed is not recorded; an agent's own account of its change is not evidence.

| File | Change | Kind | Imported by a test run |
|---|---|---|---|
| `pricing.py` | modified | code | yes |
| `tests/test_pricing.py` | modified | test |  |

Diff: `git diff 49754aeee83e`, which also shows edits made before the contract was accepted (such as the acceptance tests).

## What was verified

- `tests` (regression, advisory): passed ([output](evidence/tests.txt))
- Note: a passing check does not show that every changed line ran, and a requirement with a passing test is not thereby fully tested. The mutation check, where it ran, is the only measure here of how much the tests notice.

Each output link is a copy of the check's recorded output; report.json gives its digest and evidence record.

## What remains unverified

- `no-new-failures-locked-tests` (mandatory): fail: test_pricing::test_coupon_never_makes_total_negative passed at acceptance and fails; test_pricing::test_fixed_coupon passed at acceptance and fails ([output](evidence/no-new-failures-locked-tests.txt))
- `no-new-failures-tests` (mandatory): fail: tests.test_pricing::test_coupon_never_makes_total_negative passed at acceptance and is skipped ([output](evidence/no-new-failures-tests.txt))
- `weakening` (mandatory): fail: tests/test_pricing.py: 1 new skip or xfail ([output](evidence/weakening.txt))
- `locked-tests` (advisory): fail: checker_failed ([output](evidence/locked-tests.txt))
- Whether the requested outcome is done: no acceptance tests were agreed, so no check looked for it
- Limitation: Checkers ran with <tmp>/py/bin/python, outside the candidate identity and in no locked environment: its environment (3385 files in /Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12, <tmp>/py/lib/python3.12/site-packages) was fingerprinted at acceptance and matched before the checks ran, so later changes there are caught; changes made before acceptance, compiled __pycache__ files, and code loaded from other folders are not; environment = "uv" in ohx.toml locks it

## Decisions for you

1. A mandatory check did not pass (`weakening`, `no-new-failures-locked-tests`, `no-new-failures-tests`). Send it back to the agent with the output linked above, or, if the expected behaviour itself is wrong, agree a new contract revision. A report cannot waive a failed check.
2. Are the changed tests right? `tests/test_pricing.py` (modified). A test written with the change can only confirm what the change does.

## Details

- Contract: Locked suite at 49754aeee83e (urn:ohx:rev:4c9a1cd3-990b-4919-bdec-92ac11d7f1ae)
- Candidate: `sha256:28fe6b3aa3c3d54a7ebd86fe3a08d37feb1ab605f7f85c51de39a7827f02a1e7` (base commit 49754aeee83ef78db0a5356396dcd0929407d126)
- Gate: **fail**, evidence coverage 20%
- Verifier protection: enforced: checkers ran in the srt sandbox
- Signature: not signed

## What this verdict supports

- No regressions: no
- Tests: 3 of 4 tests checked this change
- Acceptance criteria: none: no acceptance tests were agreed, so this does not show that the task is done; add them with `ohx contract new --acceptance`

## Obligations

| Obligation | Mandatory | Status | Reasons |
|---|---|---|---|
| locked-tests | no | fail | checker_failed |
| weakening | yes | fail | checker_failed: tests/test_pricing.py: 1 new skip or xfail |
| no-new-failures-locked-tests | yes | fail | checker_failed: test_pricing::test_coupon_never_makes_total_negative passed at acceptance and fails; test_pricing::test_fixed_coupon passed at acceptance and fails |
| no-new-failures-tests | yes | fail | checker_failed: tests.test_pricing::test_coupon_never_makes_total_negative passed at acceptance and is skipped |
| tests | no | pass | none |

## Cost

- Agent work: unknown: no agent run recorded
- OpenHarnX overhead: 0 model calls, verifier time 1266 ms

## Changelog entry

- The test suite of the working tree at 49754aeee83e, locked

## Limitations

- Checkers ran with <tmp>/py/bin/python, outside the candidate identity and in no locked environment: its environment (3385 files in /Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12, <tmp>/py/lib/python3.12/site-packages) was fingerprinted at acceptance and matched before the checks ran, so later changes there are caught; changes made before acceptance, compiled __pycache__ files, and code loaded from other folders are not; environment = "uv" in ohx.toml locks it

This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.

