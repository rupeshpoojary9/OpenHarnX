# OpenHarnX threat model (M1)

- Date: 2026-09-27
- Owner: Rupesh Poojary
- Status: accepted for M1 on macOS; section "The gate" added 2026-10-04 for the public release (T81, RC-25); revisit at M2 (grants and enforcement) and on any sandbox or agent upgrade
- References: PRD 03 SEC-01 to SEC-11; Core Standard §14; Architecture §8; ADR-0005 to ADR-0007; task T05; bypass suite `spikes/boundary/bypass.py`

## Scope

M1 covers one developer, one local machine, one agent integration (Claude Code), backend and QA profiles, and no automatic merge, deployment or publication. Claims below apply to macOS 26.5.2 with `srt` 0.0.77 and Claude Code 2.1.281, as tested on 2026-09-27.

## Assets

| Asset | Why it matters |
|---|---|
| Protected acceptance material (oracle, manifests) | If it can be changed, a failing change can be made to look passing |
| Evidence store (journal, blobs) | The audit trail and the basis of every report |
| Candidate under verification | Evidence is only meaningful for the exact code checked |
| Human work in the repository | Must never be lost or overwritten |
| Credentials and secrets | Model keys, tokens, SSH keys, environment secrets |
| Budget | Money and tokens spent by agents |

## Actors and trust roles

| Role | Who in M1 | Trust |
|---|---|---|
| Implementer | The coding agent | Untrusted: may be mistaken or manipulated |
| Verifier | OpenHarnX's sandboxed test runner | Trusted only inside its sandbox profile |
| Policy owner and authority | Rupesh | Trusted |
| Evidence custodian | OpenHarnX store | Trusted process; tampering is detected by the hash chain |
| Hostile content | Repository text, tool output, fetched pages, skills | Always treated as data, never as instructions |

In M1 one person holds every human role, but the operating system separates the agent and the verifier from the protected material.

## Trust boundaries

```text
[ Rupesh ]  --contracts, approvals-->  [ OpenHarnX CLI and store ]   (trusted)
                                              |
                     launches, with env allowlist and srt profile
                          |                                  |
              [ Agent sandbox ]                    [ Verifier sandbox ]
   writes: workspace only;                 writes: its own temp dir only;
   denied: protected/, store               candidate read-only; no network
```

## Threats and M1 controls

"Prevented" means an attack was attempted and stopped in a test that also ran without the sandbox, where the attack succeeded. "Detected" means it can happen but is recorded or reported. "Out of scope" means M1 makes no claim.

| # | Threat | Control | M1 status | Evidence |
|---|---|---|---|---|
| T1 | Agent edits acceptance tests or oracle | Oracle outside the workspace or under a denied path; agent sandbox | **Prevented** when the agent is launched by OpenHarnX | B01 to B06, B11; ADR-0007 session 5 |
| T2 | Agent bypasses hooks through the shell | OS sandbox, not hooks | **Prevented** in sandbox; **detected only** without it | ADR-0006 session 2; B01 |
| T3 | Escape through symlinks, hard links or renames | Seatbelt path rules | **Prevented** | B03 to B06 |
| T4 | Escape through background processes or asking the OS to run commands (launchd, AppleScript) | Sandbox inheritance and service denials | **Prevented** | B08 to B10 |
| T5 | Verifier changes the candidate it judges | Verifier sandbox with read-only candidate | **Prevented** | B12, B12b; ADR-0005 amendment |
| T6 | Artifact substitution: evidence reused for a different candidate | Candidate digest bound to every observation; recomputed after verification | **Detected** (evidence invalidated) | ADR-0005 tests |
| T7 | Forged test results (agent claims tests passed), or a rebuilt evidence chain | Only the protected runner's observations count. Each command that writes evidence ends by signing the chain head with the owner's SSH key (`ssh-keygen -Y`, namespace `openharnx`); `ohx store check` verifies every signature and `--signer` pins the expected key; a broken signature makes the report invalid. Agents cannot read `~/.ssh`, so they cannot sign as the owner | **Detected** (added 2026-10-03, T87 item 4): a rebuilt chain breaks the signature; a chain re-signed with another key fails the pinned signer. CI signing (Sigstore) in T79 | `tests/test_signing.py` |
| T8 | Evidence store tampering | Store outside the agent's write scope; hash chain | **Prevented** for sandboxed agents; **detected** otherwise | B05; ADR-0004 tamper test |
| T9 | Secret exfiltration over the network | Verifier: no network. Agent: domain allowlist | **Prevented** for the verifier; agent limited to allowlisted domains | B14, B15 |
| T10 | Secret theft from files | `denyRead` on key locations | **Prevented** for `~/.ssh`; other secret paths must be listed per project | B13 |
| T11 | Secrets passed in environment variables | **The sandbox does not filter the environment.** OpenHarnX launches with an explicit environment allowlist | Sandbox alone: **escaped** (B16). With allowlist: **prevented** | B16 and the allowlist check |
| T12 | Prompt injection in repository or tool content | Instructions from content never change grants, obligations or policy; enforcement is in code and the OS | Structural control only; no agent-behavior test in M1 | Core §12; PRD 03 SEC-07 |
| T13 | Replayed or wrong-subject approvals | Readiness never authorizes actions in M1; no actuator exists | **Out of scope for M1** (no actuator); M2 grants | OHX-012 |
| T14 | Malicious skills | Skill supply chain (tiers, scans, sandbox trials, permission intersection) | **Out of scope for M1** (no skill loading); M2 | PRD 19 TEAM-23 to TEAM-31 |
| T15 | Loss of human work | Read-only inspection; no reset, stash or checkout | **Prevented** in tests | ADR-0005 read-only test |
| T16 | Budget overrun | Ledger records usage; enforcement is M2 | **Detected** only in M1 | COST-01 to COST-05 |
| T17 | A candidate file replaces the checker or a module it imports (VERIFY-11: a `pytest.py` turned BLOCKED into READY, also under srt) | `{python} -m <module>` checkers start with `-P` through a launcher; the module must be installed outside the candidate; the candidate is appended last to `sys.path` | **Prevented** for `-m` checkers (added 2026-10-01) | `tests/test_checker_shadowing.py`, contract 0007 |
| T18 | The interpreter and installed packages live inside the candidate directory (`.venv`), are git-ignored and so outside the candidate digest; an agent could replace the interpreter or an installed checker (reproduced 2026-10-01: a fake `.venv/bin/python` turned BLOCKED into READY) | With `environment = "uv"`, checkers run from an environment OpenHarnX builds from the accepted copy of `uv.lock` in its store (locked wheels only, no build code); a changed `uv.lock` runs nothing; without it, the report names the blind spot | **Prevented** with `environment = "uv"` for agents that cannot write the OpenHarnX home; **open** without it (added 2026-10-01, T77 item 10) | `tests/test_protected_environment.py`, contract 0011 |
| T19 | Concurrent writers fork the evidence hash chain or record one idempotency key twice (STATE-13) | Idempotency check and chain head read inside `BEGIN IMMEDIATE`; writers wait on the lock | **Prevented** on a local file system (added 2026-10-01) | `tests/test_store_concurrency.py`, contract 0008 |
| T20 | Evidence edited or removed after verification: a saved verdict, a checker output file or a protected copy (GATE-09, STATE-15, GATE-10) | `ohx report` and `ohx store check` re-check records, referenced blobs and protected copies against their digests; any problem shows the report as invalid | **Detected** (added 2026-10-01); a consistent rewrite of the unkeyed chain is not detected until signing | `tests/test_report_integrity.py`, contract 0009 |
| T21 | A symlink in the candidate points at content that changes after verification (STATE-14) | The manifest records what each symlink resolves to (content digest, missing or unresolvable) | **Detected** (added 2026-10-01): the report becomes stale | `tests/test_symlink_identity.py`, contract 0010 |
| T22 | The sandbox fails to start and its exit code is read as the checker's result (VERIFY-12; an exit 0 read as a pass) | A marker created inside the sandbox before the command; missing marker means unavailable, and the report says not enforced | **Detected** (added 2026-10-01) for verifier runs; agent runs not yet | `tests/test_sandbox_start.py`, contract 0010 |
| T23 | The agent lowers the bar instead of fixing the code: loosened check configuration, a `conftest.py` or `addopts` that changes results, new suppressions or skip markers, removed tests or assertions | Configuration and conftest files locked at acceptance; mandatory built-in `weakening` check against the accepted baseline; a contract revision is the approval path | **Detected** for the listed Python patterns (added 2026-10-02); weakened assertions, moved suppressions and import-time side effects of new test files are not | `tests/test_weakening.py`, contract 0012 |
| T24 | The agent fixes the change but breaks other tests, and the advisory suite lets it through (found in the owner's real `ohx bug` run, 2026-10-03) | Per-test results of each advisory regression suite recorded at acceptance; mandatory built-in `no-new-failures` check: a test that passed then and fails, is skipped or no longer runs blocks, and a new failing test blocks; failures already there are reported; without per-test results a suite already failing is unknown | **Detected** (added 2026-10-03, T87 item 1): blocks READY | `tests/test_regression_baseline.py` |

## The gate

The public part of OpenHarnX: `ohx gate` in CI, and `ohx verify` locally with `ohx init --lock-tests` and the Claude Code Stop hook. No model calls. The attacker is the author of the change: a contributor's pull request, or a coding agent. Claims apply to GitHub-hosted ubuntu-24.04 runners and the `ci/linux` image with srt 0.0.77, and to macOS 26.5.2 locally, as tested on the dates in `docs/gate-release-criteria.md`.

| # | Threat | Control | Status | Evidence |
|---|---|---|---|---|
| G1 | Pull request code reads the runner's secrets or token | Only the `pull_request` trigger, a read-only token, no secrets in the job; the code under review starts with none of the runner's variables | **Prevented** | `tests/test_ci_boundary.py::test_only_the_unprivileged_pull_request_trigger_is_used`, `tests/test_ci_boundary.py::test_the_code_under_review_sees_none_of_the_runner_variables`, `tests/test_workflow_guard.py::test_the_job_that_runs_pull_request_code_has_no_write_permission` |
| G2 | Pull request code changes the runner's files to influence later steps | Checks run in srt with the candidate read-only and writes limited to their own temporary folder | **Prevented** under srt on Linux; the control run without srt shows the files writable | `tests/test_ci_boundary.py::test_the_code_under_review_cannot_write_the_runner_files_under_srt`, `tests/test_ci_boundary.py::test_control_without_the_sandbox_the_runner_files_are_writable` |
| G3 | The pull request edits, skips or deletes tests, or loosens configuration, contract or policy, so that broken code passes | The verdict comes from the base: its tests are locked and run against the pull request's code; configuration is compared with the base; contract and policy in the pull request are ignored | **Prevented** for edited and deleted tests and ignored contract changes; **detected** (BLOCKED) for the weakening patterns of T23 in Python, TypeScript and Go | `tests/test_gate_ci.py::test_editing_a_test_to_match_broken_code_is_blocked`, `tests/test_gate_ci.py::test_policy_and_contract_changes_in_the_pull_request_have_no_effect`, `tests/test_gate_ci.py::test_loosened_check_configuration_is_blocked`, `tests/test_typescript_gate.py::test_editing_a_colocated_test_to_match_broken_code_is_blocked`, `tests/test_go.py::test_editing_a_go_test_to_match_broken_code_is_blocked` |
| G4 | The pull request replaces the gate, the Action or a tool the workflow uses | The gate and Action are installed from the base; every action is pinned to a commit | **Prevented** | `tests/test_workflow_guard.py::test_the_gate_is_installed_from_the_base_and_runs_sandboxed`, `tests/test_workflow_guard.py::test_every_action_is_pinned_to_a_commit`, `tests/test_action.py::test_the_repository_workflow_uses_the_action_from_the_base` |
| G5 | A file in the pull request shadows a Python module the Action or the environment builder imports (a `json.py`) | Orchestration Python runs isolated (`-I`), outside the checkout | **Prevented** (found by an external review, T88) | `tests/test_review_findings.py::test_the_action_never_imports_the_candidates_modules`, `tests/test_review_findings.py::test_building_the_protected_environment_never_imports_the_candidates_modules` |
| G6 | The pull request changes a lockfile, or its install scripts run on the runner | Packages come from the base's `uv.lock` or `package-lock.json`, installed by OpenHarnX into its own store with install scripts off; a changed lockfile runs nothing | **Prevented** with `environment = "uv"` or `"npm"`; without it the report names the blind spot | `tests/test_typescript_gate.py::test_checks_use_packages_installed_from_the_base_lockfile`, `tests/test_typescript_gate.py::test_a_changed_lockfile_runs_nothing_and_is_not_ready`, `tests/test_typescript_gate.py::test_without_the_protected_environment_the_report_names_the_blind_spot` |
| G7 | A run that collected no tests, or broke before reporting, reads as a pass | No collected tests is not READY; empty or unreadable per-test results are never a pass | **Prevented** (T88) | `tests/test_review_findings.py::test_a_gate_where_no_test_is_collected_is_not_ready`, `tests/test_review_findings.py::test_empty_per_test_results_are_never_a_pass`, `tests/test_review_findings.py::test_a_suite_that_did_not_run_properly_is_not_compared_test_by_test` |
| G8 | A test prints a forged pass line for itself | For Go, a test that both passes and fails counts as failed | **Prevented** for Go | `tests/test_go.py::test_a_test_cannot_print_its_own_pass` |
| G9 | The sandbox does not start on the runner (no user namespaces) and a check reads as passed | A marker created inside the sandbox; without it the check is unavailable and the gate is never READY | **Detected** | `tests/test_sandbox_start.py` |
| G10 | The pull request edits the workflow file so the gate does not run | GitHub runs a `pull_request` workflow from the pull request itself; the defence is a required status check and a ruleset protecting `.github/` (RC-17) | **Open** until the repository is public or on GitHub Pro (RC-17) | |
| G11 | Evidence is forged, rebuilt or has its signatures removed | Local evidence is signed with the owner's SSH key and a pinned signer must cover every record; CI evidence is to be signed as the pipeline by a job that never runs pull request code | **Detected** locally; CI signing is built but GitHub signs only public repositories (RC-24) | `tests/test_review_findings.py::test_a_pinned_signer_fails_when_signatures_were_removed`, `tests/test_signing.py::test_a_chain_re_signed_with_another_key_fails_the_pinned_signer`, `tests/test_workflow_guard.py::test_the_signing_job_never_checks_out_or_runs_pull_request_code` |
| G12 | Locally, an agent edits a locked test to get green, or removes the shared Stop hook | The locked suite and the weakening check; `.claude/settings.json` is check configuration | **Detected** (BLOCKED, and the hook sends the agent back) | `tests/test_lock_tests.py::test_an_agent_that_edits_a_test_to_get_green_is_stopped`, `tests/test_claude_hook.py::test_an_agent_that_edits_a_test_to_get_green_is_sent_back`, `tests/test_claude_hook.py::test_the_shared_claude_settings_are_checker_configuration` |
| G13 | Locally, an agent with a shell runs `ohx init --lock-tests` itself, locking its own edits, or removes the hook from `.claude/settings.local.json` | None in the Stop hook mode: Claude Code started by the owner runs as the owner, and OpenHarnX does not sandbox it. Each lock is recorded with who locked, shown by `ohx audit` | **Open** locally. The CI gate is the boundary: it locks from the base, which the agent cannot change | `tests/test_lock_tests.py::test_who_locked_the_suite_is_recorded` |
| G14 | Intended test changes are approved by someone who should not, or an approval is reused for commits pushed after it | The `ohx-approve-tests` label counts only when its last adder can push to the repository and the pull request's latest pushed commit, from GitHub's workflow run records, was the judged one when it was added; approved findings stay in the report with who approved | **Prevented** (T90b) | `tests/test_test_approval.py::test_only_people_who_can_write_approve`, `tests/test_test_approval.py::test_a_push_after_the_label_needs_the_label_again`, `tests/test_test_approval.py::test_runs_from_a_fork_with_the_same_branch_name_do_not_count`, `tests/test_test_approval.py::test_approved_a_test_that_still_exists_must_still_pass` |

What the gate does not claim: that tests are good enough to catch a wrong change (mutation checks are advisory, RC-29); safety on self-hosted or shared runners, which keep state between jobs; Windows; and protection for languages other than Python, TypeScript, JavaScript and Go.

## Operational requirements that follow

1. Launch every verifier and every OpenHarnX-launched agent with an **explicit environment allowlist**, never the caller's full environment (T11).
2. Give `srt` a **short `TMPDIR`**, such as `/tmp`. Its Unix socket path must stay under the macOS limit of about 104 characters, or it fails to start. Set the verifier's own `TMPDIR` inside the sandboxed command.
3. Keep protected material and the store **outside** or **explicitly denied** in every agent profile.
4. Report which protection mode applied on every run: **enforced** (sandboxed) or **observed** (hooks only).
5. Pin `srt` and Claude Code versions, and rerun the bypass suite on any upgrade.

## Residual risks and open items

- **Agent-profile allowlist:** the profile used in T03 allowed writes to the Claude configuration directory and several temporary paths so that Claude Code could run. An agent could change its own Claude settings, for example hooks, which persist after the session. Narrow this before M1 acceptance.
- **Network allowlist for agents:** it allows the model provider's domains, which an agent could still use to send data. That is inherent to using a hosted model and is declared, not prevented.
- **Platforms:** Linux is tested on GitHub-hosted runners and in the `ci/linux` image (the gate, since 2026-10-03); agent runs on Linux and anything on Windows are untested.
- **Kernel and sandbox vulnerabilities** are out of scope.
- **Candidate code inside the checker (T17 residual):** a `conftest.py`, pytest plugin or `addopts` setting in the candidate still runs inside pytest; since T77 item 9 (T23) any change to them after acceptance blocks, but what was accepted still runs. A module the checker imports only optionally, and that is installed nowhere, can still be supplied by the candidate. Commands that are not `{python} -m` (console scripts such as `{bindir}/lint-imports`) are not rewritten; they do not put the candidate first on `sys.path`, but they are not covered by the T17 tests.
- **Deliberate adversarial agents** probing the policy over long sessions were not tested; the suite tests known techniques only.
