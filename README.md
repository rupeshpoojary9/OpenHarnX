<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/openharnx-logo-dark.png">
    <img src="docs/assets/openharnx-logo-light.png" alt="OpenHarnX" width="600">
  </picture>
</p>

# OpenHarnX

OpenHarnX is an open-source verifier for changes written by coding agents such as Claude Code and Codex. Keep your agent. OpenHarnX locks the tests you agreed on, runs every check in a sandbox and gives a verdict with evidence, opened by a review brief: what was asked, what changed, what passed, what remains unverified and what needs your judgment. The agent never grades its own work, and no model is called.

**Early release (0.1.0).** It has been tested on its own development, on replays of public agent runs and pull requests, and with simulated users. It has no production users yet; nothing here claims that reviews get faster or that changes are safe.

## Quick start

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/), git and, for the sandbox, Node 20 or later.

```bash
# 1. Install OpenHarnX (pinned) and the sandbox it runs checks in
uv tool install git+https://github.com/rupeshpoojary9/OpenHarnX@v0.1.0
npm install -g @anthropic-ai/sandbox-runtime@0.0.77     # provides `srt`
ohx doctor

# 2. Watch it catch a cheat: a scripted agent rewrites one test and skips another,
#    plain pytest says it all passes, OpenHarnX says BLOCKED; the real fix passes
git clone https://github.com/rupeshpoojary9/OpenHarnX && cd OpenHarnX
uv run --no-project --with pytest python examples/cheat-demo/demo.py

# 3. Protect your own project (a git repository with a pytest suite)
cd /path/to/your/project
ohx init --lock-tests            # the suite as it is now becomes the contract
ohx hook install                 # optional: Claude Code verifies when it says it is done

# 4. Let your agent make a change, then
ohx verify --sandbox srt         # READY, NO REGRESSIONS, BLOCKED, UNKNOWN or INVALID
ohx report                       # the review brief and the evidence behind it
```

To check that a specific task is done, not only that nothing broke, agree acceptance tests for it first: `ohx contract new --title ... --summary ... --acceptance tests/test_task.py --accept`. With them a passing change is READY; without them it is NO REGRESSIONS.

## Supported in 0.1.0

The release boundary is [docs/gate-release-criteria.md](docs/gate-release-criteria.md): Python projects tested with pytest, on macOS (arm64) locally and on Linux in CI ([docs/ci](docs/ci/README.md): a GitHub Action, GitLab and Jenkins examples), with `srt` as the sandbox. On anything else OpenHarnX makes no claim of protection.

- **Locked tests.** `ohx init --lock-tests` makes the existing suite the contract; `ohx contract new --accept` adds acceptance tests for a task. Editing, skipping, deleting or weakening a locked test, loosening check configuration, or breaking a test that passed before is BLOCKED. Checkers supplied by the candidate cannot replace the real ones.
- **Verdicts that say what they support.** READY needs agreed acceptance tests; NO REGRESSIONS means nothing that passed before broke and nothing shows the task is done. A check that is missing, crashed or timed out is UNKNOWN, never a pass. Readiness never authorizes a merge or a deploy.
- **The review brief.** Every report opens with what was asked, which files changed, what was verified (each claim linked to the check's output), what remains unverified and the decisions left to you ([examples](docs/tasks/T96.md#before-and-after)).
- **Claude Code.** `ohx hook install` verifies when the agent says it is done. A BLOCKED agent is sent back with the agreed tests that failed, the error lines and where the full output is (at most three times in a row); every verdict reaches you as a one-line message. With `claude -p`, that message appears only in `--output-format stream-json` (plain `json` carries no hook output); `ohx report` always has it.
- **The checker's interpreter.** Checks run with the project's own: `python` in `ohx.toml`, else its `.venv` or `venv`, else the active virtual environment. Without `environment = "uv"` (a protected environment built from `uv.lock`), that interpreter's environment is fingerprinted when the contract is accepted, and any later change makes every check invalid, naming the files.
- **Evidence.** A hash-chained local store signed with your SSH key; `ohx report`, `ohx audit` and `ohx store check`. In CI the report is signed by the pipeline (Sigstore).
- **History.** `ohx history --last 20` shows what the gate would have said about changes already merged.

Commit `ohx.toml` and `contracts/`; keep `.claude/settings.local.json` (written by `ohx hook install`, with paths on your machine) out of git. A slow suite runs in parallel with `pytest_args = ["-n", "auto"]` in `ohx.toml`, and `suite_timeout_s` (300 seconds unless set) is how long each whole suite OpenHarnX runs may take; under the sandbox on a CI runner a suite can be several times slower than on your machine.

## Experimental

Working and tested, outside the 0.1.0 boundary: TypeScript and JavaScript projects (Vitest, Jest, `node --test`; in CI with `environment = "npm"` protecting `node_modules`), Go projects (`go test`), an advisory mutation check (changes the lines your change touched and reports any change the acceptance tests did not notice; 120 seconds unless `mutation_budget_s` says otherwise), `ohx bug` (an agent investigates a bug read-only, you approve the rule and tests, the agent fixes, the gate verifies) and `ohx trace` (requirement coverage).

**Not supported:** Linux outside CI, Windows, pnpm and Yarn lockfiles, Playwright, more than one agent at a time.

## Specifications

The research, product requirements and roadmap are kept in the owner's private notes and are not published. What matters for the code is here: implementation decisions in [`docs/adr/`](docs/adr/), and for each task the commands, results and limitations in [`docs/tasks/`](docs/tasks/). [ADR-0001](docs/adr/0001-source-location-and-spec-home.md) explains the split.

## Development setup

Requires Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and git.

```bash
uv sync                 # create the environment from uv.lock
./scripts/check.sh      # format, lint, strict types, layer rules, tests
uv run ohx doctor       # check the local environment
```

Install a release (pinned; see [docs/releasing.md](docs/releasing.md)), or the command from a clone for local use, and remove it again:

```bash
uv tool install git+https://github.com/rupeshpoojary9/OpenHarnX@v0.1.0   # a release
uv tool install .                                                        # from a clone
ohx --version
uv tool uninstall openharnx
```

Security reports: see [SECURITY.md](SECURITY.md).

## Contributing and roadmap

Issues and small pull requests are welcome; a wrong verdict is the most useful report. [CONTRIBUTING.md](CONTRIBUTING.md) explains how to report one, set up, and how the gate treats a pull request. [ROADMAP.md](ROADMAP.md) lists what comes next and what is not planned.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success; READY or NO REGRESSIONS |
| 10 | A valid result that does not pass: BLOCKED, UNKNOWN, INVALID or STALE |
| 2 | Usage or input error |
| 1 | Internal failure |

## License

Apache-2.0. See [LICENSE](LICENSE). Dependencies and their licenses are listed in [docs/dependencies.md](docs/dependencies.md).
