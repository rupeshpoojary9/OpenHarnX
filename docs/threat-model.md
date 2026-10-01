# OpenHarnX threat model (M1)

- Date: 2026-09-27
- Owner: Rupesh Poojary
- Status: accepted for M1 on macOS; revisit at M2 (grants and enforcement) and on any sandbox or agent upgrade
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
| T7 | Forged test results (agent claims tests passed) | Only the protected runner's observations count; the runner signs them (T09) | Designed; signing lands in T09 | Architecture §8.4 |
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
| T18 | The interpreter and installed packages live inside the candidate directory (`.venv`), are git-ignored and so outside the candidate digest; an agent could edit the installed checker | None yet | **Open** (found 2026-10-01, T77 item 10) | Report line "ignored file(s) present and not in the candidate identity" |
| T19 | Concurrent writers fork the evidence hash chain or record one idempotency key twice (STATE-13) | Idempotency check and chain head read inside `BEGIN IMMEDIATE`; writers wait on the lock | **Prevented** on a local file system (added 2026-10-01) | `tests/test_store_concurrency.py`, contract 0008 |
| T20 | Evidence edited or removed after verification: a saved verdict, a checker output file or a protected copy (GATE-09, STATE-15, GATE-10) | `ohx report` and `ohx store check` re-check records, referenced blobs and protected copies against their digests; any problem shows the report as invalid | **Detected** (added 2026-10-01); a consistent rewrite of the unkeyed chain is not detected until signing | `tests/test_report_integrity.py`, contract 0009 |
| T21 | A symlink in the candidate points at content that changes after verification (STATE-14) | The manifest records what each symlink resolves to (content digest, missing or unresolvable) | **Detected** (added 2026-10-01): the report becomes stale | `tests/test_symlink_identity.py`, contract 0010 |
| T22 | The sandbox fails to start and its exit code is read as the checker's result (VERIFY-12; an exit 0 read as a pass) | A marker created inside the sandbox before the command; missing marker means unavailable, and the report says not enforced | **Detected** (added 2026-10-01) for verifier runs; agent runs not yet | `tests/test_sandbox_start.py`, contract 0010 |

## Operational requirements that follow

1. Launch every verifier and every OpenHarnX-launched agent with an **explicit environment allowlist**, never the caller's full environment (T11).
2. Give `srt` a **short `TMPDIR`**, such as `/tmp`. Its Unix socket path must stay under the macOS limit of about 104 characters, or it fails to start. Set the verifier's own `TMPDIR` inside the sandboxed command.
3. Keep protected material and the store **outside** or **explicitly denied** in every agent profile.
4. Report which protection mode applied on every run: **enforced** (sandboxed) or **observed** (hooks only).
5. Pin `srt` and Claude Code versions, and rerun the bypass suite on any upgrade.

## Residual risks and open items

- **Agent-profile allowlist:** the profile used in T03 allowed writes to the Claude configuration directory and several temporary paths so that Claude Code could run. An agent could change its own Claude settings, for example hooks, which persist after the session. Narrow this before M1 acceptance.
- **Network allowlist for agents:** it allows the model provider's domains, which an agent could still use to send data. That is inherent to using a hosted model and is declared, not prevented.
- **Platforms:** Linux and Windows sandbox paths are untested.
- **Kernel and sandbox vulnerabilities** are out of scope.
- **Candidate code inside the checker (T17 residual):** a `conftest.py`, pytest plugin or `addopts` setting in the candidate still runs inside pytest and can change its result; that is T77 item 9 and owner proposal 2. A module the checker imports only optionally, and that is installed nowhere, can still be supplied by the candidate. Commands that are not `{python} -m` (console scripts such as `{bindir}/lint-imports`) are not rewritten; they do not put the candidate first on `sys.path`, but they are not covered by the T17 tests.
- **Deliberate adversarial agents** probing the policy over long sessions were not tested; the suite tests known techniques only.
