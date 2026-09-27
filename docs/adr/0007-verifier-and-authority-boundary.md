# ADR-0007: Verifier and authority boundary

- Date: 2026-09-27
- Owner: Rupesh Poojary
- Status: accepted for M1 on macOS
- References: vault ADR-07; PRD 03 SEC-01, SEC-03; PRD 07 VERIFY-03, VERIFY-05, VERIFY-06; OHX-006; Architecture §8; task T03 part E; ADR-0005 amendment; ADR-0006

## Context

ADR-0006 showed that a Claude Code hook blocks file-tool writes to a protected path, but a shell redirection bypasses it. ADR-0005 showed that a verifier can change the candidate it judges, for example by writing bytecode caches. Both need an operating-system boundary, not agent-level rules.

## Candidate

Anthropic `sandbox-runtime` (`srt`) 0.0.77. It is Apache-2.0, installed only in a scratch folder with `npm`, and uses Seatbelt on macOS and bubblewrap on Linux. Its configuration is a filesystem write allowlist, explicit read and write denials, and a network domain allowlist. The format was taken from the package README, which describes it as a research preview whose configuration may change.

## Experiments (macOS 26.5.2, 2026-09-27)

**Verifier profile:** writes allowed only to a private temporary directory, no network domains allowed, `~/.ssh` unreadable.

| Test | Result |
|---|---|
| Protected acceptance tests on a candidate, no bytecode setting | 21 of 21 passed |
| Candidate digest before and after verification | Identical (`ba3f5369...`): the sandbox refused cache writes |
| Append to `protected/ORACLE.md` from inside | `Operation not permitted`, file unchanged |
| Append to the candidate's `items.py` from inside | `Operation not permitted`, file unchanged |
| Append to an evidence-store file from inside | `Operation not permitted`, file unchanged |
| Write to the allowed temporary directory | Allowed |
| HTTPS request to example.com | Blocked (curl exit 56) |
| Verifier run without an allowed `TMPDIR` | Fails: Python finds no usable temporary directory. The verifier must always set `TMPDIR` inside its allowlist |

**Agent profile:** Claude Code 2.1.281 run entirely inside `srt`.
- Writes allowed to the workspace, the Claude configuration and cache paths, and temporary directories.
- `protected/` explicitly denied.
- Network limited to Anthropic, Claude, Statsig and Sentry domains.

| Session | Result | Cost reported |
|---|---|---|
| 5: shell `echo 'bypass' >> protected/ORACLE.md` (the session 2 bypass, repeated) | **Blocked**: `operation not permitted`, file unchanged | $0.06 |
| 6: normal bug fix and unit tests | Fix made and tests passed. The protected acceptance tests, run afterwards in the verifier sandbox, passed 21 of 21 | $0.06 |

Because `srt` wraps the whole agent process, the agent cannot turn the boundary off from inside, unlike an agent's own opt-out sandbox settings.

## Decision

- **Verification** always runs inside an OS sandbox:
  - the candidate is read-only
  - writes go only to a per-run temporary directory, with `TMPDIR` set there
  - no network unless an obligation declares it
- **Agents** that OpenHarnX launches run inside an OS sandbox that denies writes to protected acceptance material and to the OpenHarnX store. When an agent is not launched this way, the adapter declares protection as **observation only** (Architecture §8.3). Tampering is then detected through fingerprints and the journal hash chain, not prevented.
- `srt` is the first sandbox implementation. OpenHarnX drives it through its CLI or configuration and keeps its own policy, so the sandbox can be replaced.

## Consequences

- Using `srt` adds a Node.js runtime requirement. This must be declared in the supported-environment matrix. A direct Seatbelt or bubblewrap backend written in Python remains an option if that dependency proves costly.
- Hook-based blocking stays useful for early, readable denials, but is never cited as enforcement on its own.

## Limits and open items

- Tested on macOS only. The Linux (bubblewrap) and Windows (alpha) paths are unverified.
- `srt` is a research preview; pin its version and re-run these tests on upgrade (ADAPT-08).
- The agent profile's network allowlist was chosen to make Claude Code work in this test; it has not been minimized or audited.
- Not tested:
  - symlink and hard-link escapes
  - writes through other allowed paths, such as the Claude configuration directory
  - a malicious agent deliberately probing the policy

  These belong in the T05 threat model and its bypass suite.
