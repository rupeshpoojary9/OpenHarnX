# Public gate release criteria (T86)

The gate is the free, open-source part of OpenHarnX: a locked contract, protected acceptance tests, the weakening and regression checks, and a verdict, with no model calls in the core. This document is its release boundary. The gate is released publicly only when every criterion marked `required` is met. Each criterion that is met names the tests that prove it; each one that is not names the task that owns it. `tests/test_release_criteria.py` keeps this document consistent with the code.

Out of scope for this release: `ohx bug` (agent-driven fixes), `ohx trace` (requirement coverage) and every M1 capability beyond the gate. The gate does not satisfy T17 (full M1 acceptance).

## Release decision

**Releasable now: no**
Blocking: RC-17, RC-24, RC-25.

## Supported environment

The first release supports Python projects tested with pytest, on macOS (arm64) locally and on Linux in CI, with `srt` as the sandbox. The verifier itself makes no network calls and no model calls.

| ID | Criterion | Release | Status | Evidence | Owner |
|---|---|---|---|---|---|
| RC-01 | Sandboxed verification works on macOS arm64 with srt; the checker cannot be replaced from the candidate under the real sandbox | required | met | `tests/test_checker_shadowing.py::test_candidate_file_cannot_replace_the_checker_under_srt`, `tests/test_skeleton_e2e.py::test_sandboxed_verification` (both run with OHX_SRT set; every OpenHarnX commit since T77 was verified READY under srt) | |
| RC-02 | Sandboxed verification works on a Linux CI runner, validated in CI, not at packaging | required | met | `tests/test_gate_ci.py::test_genuine_change_with_a_new_test_passes`, `tests/test_gate_ci.py::test_editing_a_test_to_match_broken_code_is_blocked` (the same cases on GitHub Actions ubuntu-24.04, 2026-10-03: run 37116149741 READY and run 37116150695 BLOCKED, both with the srt sandbox enforced) | |
| RC-03 | A Python project with a uv lockfile is checked from a protected environment built outside the candidate | required | met | `tests/test_protected_environment.py::test_tampered_candidate_interpreter_cannot_pass_buggy_code`, `tests/test_protected_environment.py::test_changed_lockfile_runs_nothing_and_is_not_ready` | |
| RC-04 | Without a protected environment, the report names that blind spot instead of claiming protection | required | met | `tests/test_protected_environment.py::test_without_a_protected_environment_the_report_names_the_blind_spot` | |

## Trust boundary

Trusted: the accepted contract and the protected copies of its acceptance tests, held in the OpenHarnX store outside the repository; the OpenHarnX verifier; the protected checker environment; the owner's signing key. Untrusted: everything in the candidate, including tests and configuration it adds, and anything an agent wrote. The verifier runs checkers in a sandbox with no network, writes only to its own run directory, and cannot read `~/.ssh` or OpenHarnX's keys.

| ID | Criterion | Release | Status | Evidence | Owner |
|---|---|---|---|---|---|
| RC-05 | Acceptance tests are judged from the protected copy; editing the workspace copy changes nothing | required | met | `tests/test_skeleton_e2e.py::test_variant_verdicts`, `tests/test_bug.py::test_agent_that_edits_the_test_stays_blocked` | |
| RC-06 | A candidate file cannot replace the checker or a module it imports | required | met | `tests/test_checker_shadowing.py::test_candidate_file_cannot_replace_the_checker`, `tests/test_checker_shadowing.py::test_checker_found_only_in_the_candidate_is_not_a_pass` | |
| RC-07 | The verifier does not change the candidate it judges | required | met | `tests/test_skeleton_e2e.py::test_verification_leaves_the_repository_untouched` | |
| RC-08 | Checkers see an allowlisted environment, never the caller's secrets | required | met | `tests/test_sandbox_env.py::test_child_gets_proxy_and_allowlist_but_not_caller_secrets` | |
| RC-30 | A change to the candidate during verification invalidates every result of that run | required | met | `tests/test_gate_ci.py::test_a_candidate_changed_during_verification_is_invalid` | |
| RC-09 | Evidence is signed by the owner's key; a rebuilt or re-signed chain is detected | required | met | `tests/test_signing.py::test_a_rebuilt_chain_breaks_the_signature`, `tests/test_signing.py::test_a_chain_re_signed_with_another_key_fails_the_pinned_signer` | |

## What READY means

READY means: for this exact candidate (a digest over every tracked and untracked, non-ignored file, including what symlinks resolve to), under this exact contract revision, every mandatory check ran under the stated protection and passed, no protected material or check configuration was weakened since acceptance, and no test that passed at acceptance fails now. READY also needs at least one mandatory acceptance check in the contract: agreed tests for the requested behaviour, and they passed. When every mandatory check passed but the contract has no acceptance check (`ohx init --lock-tests`, or `ohx gate` without a contract), the verdict is NO REGRESSIONS: nothing that passed before broke, and nothing shows the task is done (T91, owner decision 2026-10-04). Both exit 0; the report lists each claim and the tests that still fail as before. Neither means the change is correct beyond what the tests check, that it is safe to merge or deploy, or that anyone approved it. Any check that could not run gives unknown, which is never a pass. A report authorizes nothing.

| ID | Criterion | Release | Status | Evidence | Owner |
|---|---|---|---|---|---|
| RC-10 | Any mandatory check that is missing, timed out, crashed or could not start gives unknown, never a pass | required | met | `tests/test_gate.py::test_any_mandatory_non_pass_never_passes`, `tests/test_gate.py::test_timeout_is_unknown_not_fail_or_pass`, `tests/test_sandbox_start.py::test_sandbox_that_did_not_start_is_unknown_and_not_enforced` | |
| RC-11 | The verdict is bound to the candidate digest, including uncommitted work and symlink targets | required | met | `tests/test_skeleton_e2e.py::test_candidate_digest_tracks_uncommitted_work`, `tests/test_symlink_identity.py::test_changing_a_symlinked_file_outside_the_repo_makes_the_report_stale` | |
| RC-12 | Reports name the blind spots that apply: an unprotected interpreter, and whether the evidence is signed (the ignored-file count and suites without a baseline are listed too, not yet tested) | required | met | `tests/test_protected_environment.py::test_without_a_protected_environment_the_report_names_the_blind_spot`, `tests/test_signing.py::test_the_report_says_it_is_signed` | |

## Positive and negative controls

Every negative control is paired with a positive one, so a gate that blocks everything fails these criteria too.

| ID | Criterion | Release | Status | Evidence | Owner |
|---|---|---|---|---|---|
| RC-13 | Positive controls: a genuine fix is READY, including next to an unrelated failure that was already there, and adding new tests needs no approval | required | met | `tests/test_skeleton_e2e.py::test_report_is_ready_when_nothing_changed`, `tests/test_regression_baseline.py::test_fix_with_a_failure_that_was_already_there_is_ready`, `tests/test_weakening.py::test_control_a_new_test_file_needs_no_approval` | |
| RC-14 | Negative controls, weakening: new suppressions or skip markers, loosened configuration, removed assertions, deleted tests, a conftest or addopts that changes results are blocked | required | met | `tests/test_weakening.py::test_new_skip_marker_is_blocked`, `tests/test_weakening.py::test_loosened_lint_config_is_blocked`, `tests/test_weakening.py::test_removed_assertions_are_blocked`, `tests/test_weakening.py::test_deleted_test_file_is_blocked`, `tests/test_weakening.py::test_new_conftest_that_forces_passes_is_blocked`, `tests/test_weakening.py::test_pytest_addopts_that_deselects_tests_is_blocked` | |
| RC-15 | Negative controls, collateral damage: a change that breaks a test that passed at acceptance, or stops it running, is blocked | required | met | `tests/test_regression_baseline.py::test_fix_that_breaks_another_test_is_blocked`, `tests/test_regression_baseline.py::test_test_that_no_longer_runs_is_blocked` | |
| RC-16 | A reproducible cheat demo: an agent weakens a test and claims success, the gate blocks it, the real fix passes | required | met | `tests/test_cheat_demo.py::test_the_demo_shows_green_tests_blocked_and_the_real_fix_ready`, `tests/test_cheat_demo.py::test_the_demo_fails_when_a_verdict_is_not_what_it_shows` (`examples/cheat-demo/`, scripted with no model; run under srt 2026-10-04: plain pytest 3 passed, 1 skipped, BLOCKED naming both edited tests and the skip, the genuine change passing, NO REGRESSIONS since T91) | |

## Stale and corrupt evidence

| ID | Criterion | Release | Status | Evidence | Owner |
|---|---|---|---|---|---|
| RC-31 | In CI, every locked base test runs as it would in the repository, including tests that find files relative to their own location | required | met | `tests/test_locked_in_tree.py::test_editing_a_location_relative_test_to_match_broken_code_is_blocked`, `tests/test_locked_in_tree.py::test_a_copy_that_differs_from_the_judged_candidate_is_refused` (on OpenHarnX itself, 2026-10-03: the 12 tests that failed in the locked run in CI now pass, locally and on GitHub Actions in run 37120096875) | |
| RC-20 | A report for an earlier candidate or contract revision is shown as stale, never as ready | required | met | `tests/test_skeleton_e2e.py::test_report_is_stale_after_source_edit`, `tests/test_skeleton_e2e.py::test_report_is_stale_after_new_contract` | |
| RC-21 | An edited verdict, a missing or changed evidence file, or a changed protected copy makes the report invalid | required | met | `tests/test_report_integrity.py::test_edited_saved_verdict_is_not_ready`, `tests/test_report_integrity.py::test_deleted_evidence_file_is_not_ready`, `tests/test_report_integrity.py::test_changed_protected_copy_is_not_ready` | |
| RC-22 | Concurrent writers keep one unbroken evidence chain | required | met | `tests/test_store_concurrency.py::test_concurrent_appends_keep_one_unbroken_chain` | |

## Approved checker changes

A change to check configuration, protected tests or the checker environment is accepted only through a contract revision, which records who accepted it.

| ID | Criterion | Release | Status | Evidence | Owner |
|---|---|---|---|---|---|
| RC-23 | A configuration change blocks until a contract revision accepts it; the revision records who accepted | required | met | `tests/test_weakening.py::test_control_an_accepted_revision_approves_a_config_change`, `tests/test_audit_trail.py::test_acceptance_and_approval_name_who_did_them` | |

## Untrusted pull requests

The gate in CI runs code from pull requests by strangers. No model calls and no secrets remove one cost path; they do not isolate untrusted code.

| ID | Criterion | Release | Status | Evidence | Owner |
|---|---|---|---|---|---|
| RC-17 | The contract, protected tests and verifier come from the protected base branch, never from the pull request | required | not met | | T79 |
| RC-18 | Untrusted runs use ephemeral, unprivileged runners: no privileged checkout of pull request code, no persistent self-hosted runner for forks, controlled caches, network and resource limits | required | met | `tests/test_ci_boundary.py::test_only_the_unprivileged_pull_request_trigger_is_used`, `tests/test_ci_boundary.py::test_every_job_runs_on_a_github_hosted_runner_with_a_time_limit`, `tests/test_ci_boundary.py::test_no_shared_caches`, `tests/test_workflow_guard.py::test_the_job_that_runs_pull_request_code_has_no_write_permission`, `tests/test_sandbox_env.py::test_child_gets_proxy_and_allowlist_but_not_caller_secrets` (owner decision 2026-10-03: when the repository goes public, workflows from all outside collaborators need approval, a repository setting outside these tests) | T79 |
| RC-19 | The verdict is published without exposing write permissions to the candidate process: job outputs or artifacts first; any privileged publisher treats result data as untrusted and never executes it | required | met | `tests/test_ci_boundary.py::test_no_job_can_post_comments_statuses_or_push`, `tests/test_ci_boundary.py::test_the_code_under_review_sees_none_of_the_runner_variables`, `tests/test_ci_boundary.py::test_the_code_under_review_cannot_write_the_runner_files_under_srt`, `tests/test_ci_boundary.py::test_control_without_the_sandbox_the_runner_files_are_writable`, `tests/test_workflow_guard.py::test_the_signing_job_never_checks_out_or_runs_pull_request_code` (published as exit code, job summary and artifact; owner decision 2026-10-03: no pull request comment for now; the srt test passed on macOS and on Linux in the ohx-linux image) | T79 |
| RC-24 | Evidence produced in CI is signed as the pipeline (Sigstore keyless), and reports say which kind of signature they carry (built 2026-10-03 as a GitHub artifact attestation in a separate job, guarded by `tests/test_workflow_guard.py`; GitHub signs only in public repositories below Enterprise Cloud, so the first real signature comes when the repository is public) | required | not met | | T81 |

## Not supported

Stated in the README and here; a project outside this list gets no claim of protection.

| ID | Criterion | Release | Status | Evidence | Owner |
|---|---|---|---|---|---|
| RC-25 | A public install with pinned releases, a security contact and a published threat model | required | not met | | T81 |
| RC-26 | TypeScript and Go projects (Vitest, Jest, Playwright, go test) and their weakening patterns | later | not met | | T82 |
| RC-27 | Windows, and Linux outside CI | later | not met | | T79, T82 |
| RC-28 | Verification fast enough for many agent loops a day | later | not met | | T80 |
| RC-29 | Mutation checks that the locked tests catch plausible wrong fixes | later | met | `tests/test_mutation.py::test_weak_tests_let_a_wrong_fix_survive_and_the_verdict_is_unchanged`, `tests/test_mutation.py::test_strong_tests_kill_every_mutant` (advisory: survivors are reported, the verdict is unchanged) | |
