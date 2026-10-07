# OpenHarnX report: READY

## Requested outcome

**Percentage coupons** (task): order_total takes a percentage coupon as well as a fixed one

Stated in contract revision `urn:ohx:rev:927da7d1-24b7-47d2-98c5-b6be4d85c947`, accepted by Shop Owner <owner@example.com>. It is checked only through the acceptance tests below, not read for meaning.

## What changed

Observed: 1 file(s) differ, by content digest, from the files accepted with the contract (base commit `5550db958067`). Why each changed is not recorded; an agent's own account of its change is not evidence.

| File | Change | Kind | Imported by a test run |
|---|---|---|---|
| `pricing.py` | modified | code | yes |

Diff: `git diff 5550db958067`, which also shows edits made before the contract was accepted (such as the acceptance tests).

## What was verified

- `acceptance-test_percent_coupon` (acceptance, mandatory): passed, 2 of 2 agreed tests: test_percent_coupon, test_percent_then_fixed_coupon ([output](evidence/acceptance-test_percent_coupon.txt))
- `no-new-failures-locked-tests` (built-in, mandatory): every test in `locked-tests` that passed before passes ([output](evidence/no-new-failures-locked-tests.txt))
- `no-new-failures-tests` (built-in, mandatory): every test in `tests` that passed before passes ([output](evidence/no-new-failures-tests.txt))
- `weakening` (built-in, mandatory): no removed test or assertion, new skip, new suppression or loosened check configuration was found ([output](evidence/weakening.txt))
- `locked-tests` (regression, advisory): passed ([output](evidence/locked-tests.txt))
- `tests` (regression, advisory): passed ([output](evidence/tests.txt))
- Note: a passing check does not show that every changed line ran, and a requirement with a passing test is not thereby fully tested. The mutation check, where it ran, is the only measure here of how much the tests notice.

Each output link is a copy of the check's recorded output; report.json gives its digest and evidence record.

## What remains unverified

- `mutation` (advisory): fail: 2 of 8 mutants of changed lines survived: pricing.py:9 `0` -> `1`; pricing.py:14 `0` -> `1` ([output](evidence/mutation.txt))
- Limitation: Checkers ran with <tmp>/py/bin/python, outside the candidate identity and in no locked environment: its environment (3385 files in /Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12, <tmp>/py/lib/python3.12/site-packages) was fingerprinted at acceptance and matched before the checks ran, so later changes there are caught; changes made before acceptance, compiled __pycache__ files, and code loaded from other folders are not; environment = "uv" in ohx.toml locks it

## Decisions for you

1. Do these changed lines need a test? Changing them did not make any acceptance test fail: 2 of 8 mutants of changed lines survived: pricing.py:9 `0` -> `1`; pricing.py:14 `0` -> `1`

## Details

- Contract: Percentage coupons (urn:ohx:rev:927da7d1-24b7-47d2-98c5-b6be4d85c947)
- Candidate: `sha256:777cbcc8ca4232904b928c7b55788c7d908136683e7f9518e7a71584a3a294e3` (base commit 5550db958067a660a0daa95ad757937b1366a5b3)
- Gate: **pass**, evidence coverage 85%
- Verifier protection: enforced: checkers ran in the srt sandbox
- Signature: not signed

## What this verdict supports

- No regressions: yes, every test that passed before still passes
- Tests: 5 of 5 tests checked this change
- Acceptance criteria: met

## Obligations

| Obligation | Mandatory | Status | Reasons |
|---|---|---|---|
| mutation | no | fail | checker_failed: 2 of 8 mutants of changed lines survived: pricing.py:9 `0` -> `1`; pricing.py:14 `0` -> `1` |
| acceptance-test_percent_coupon | yes | pass | none |
| locked-tests | no | pass | none |
| tests | no | pass | none |
| weakening | yes | pass | none |
| no-new-failures-locked-tests | yes | pass | none |
| no-new-failures-tests | yes | pass | none |

## Cost

- Agent work: unknown: no agent run recorded
- OpenHarnX overhead: 0 model calls, verifier time 2749 ms

## Changelog entry

- order_total takes a percentage coupon as well as a fixed one

## Limitations

- Checkers ran with <tmp>/py/bin/python, outside the candidate identity and in no locked environment: its environment (3385 files in /Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12, <tmp>/py/lib/python3.12/site-packages) was fingerprinted at acceptance and matched before the checks ran, so later changes there are caught; changes made before acceptance, compiled __pycache__ files, and code loaded from other folders are not; environment = "uv" in ohx.toml locks it

This report authorizes nothing. It is evidence of readiness, not permission to merge, deploy or publish.

