# Roadmap

Where OpenHarnX is going. No dates: work is taken in order and shipped when it is verified. Priorities move with what users report, so if something here matters to you, or something missing does, open an issue or send a [trial report](https://github.com/rupeshpoojary9/OpenHarnX/issues/new?template=trial-report.yml).

What is released and supported today is in the [README](https://github.com/rupeshpoojary9/OpenHarnX#supported-in-012) and the [release criteria](https://github.com/rupeshpoojary9/OpenHarnX/blob/main/docs/gate-release-criteria.md).

## Released

- [x] **0.1.0:** locked tests, sandboxed verification, verdicts that say what they support, the review brief, the Claude Code Stop hook, the CI gate (GitHub Action, GitLab and Jenkins examples), signed evidence locally and in CI, a fingerprinted checker interpreter.
- [x] **0.1.1:** published to PyPI (`uv tool install openharnx`) through trusted publishing; a README that works as the PyPI page; the logo follows GitHub's theme.
- [x] **0.1.2:** `ohx doctor` finds setup problems and says the fix; a troubleshooting guide; documentation-only pull requests skip the gate's suite; code that checks whether a test runner is running is flagged; the gate runs a suite once when no test file changed; an experimental OpenCode plugin; a repeatable Linux trial outside CI.

## Next (0.1.x)

- [x] **Code that detects the test runner.** Flag changed code that behaves differently when pytest is running (for example by checking `sys.modules` or `PYTEST_CURRENT_TEST`), a way for a change to pass every test and fail in use.
- [ ] **Approval and CI documentation.** The GitLab example fetching approval notes, which SSH key `ohx approve-tests` signs with, and a BLOCKED report that says how test changes are approved.
- [ ] **The checker's interpreter.** Also fingerprint folders that a `.pth` file in its environment points to.
- [x] **Faster CI.** The gate runs the whole suite up to three times under the sandbox; reuse what can be reused.
- [ ] **`ohx doctor`** checks the sandbox and JavaScript setups, not only Python and git.

## Agent integrations

Every agent can be checked today with `ohx verify` or the CI gate, because OpenHarnX reads the change and the test runs, not the agent. A built-in integration does what the Claude Code Stop hook does: verify when the agent says it is done, send a blocked agent back with what failed, and tell you the verdict. Each depends on the agent offering a way to run a command when it finishes; that is checked per agent before anything is built, and an integration ships only after a live run with that agent is recorded.

- [x] **Claude Code:** Stop hook, tested end to end.
- [ ] **OpenCode**, including with a model hosted on your own machine or network, where the sandbox can show that nothing leaves it. The plugin is built (`ohx hook install --agent opencode`, experimental); it is ticked once a live run is recorded.
- [ ] **Codex.**
- [ ] **Cursor.**
- [ ] **Antigravity** and others, in the order trial reports ask for them.

## Being considered (0.2)

- [ ] **TypeScript, JavaScript and Go as supported**, not experimental, including pnpm and Yarn lockfiles.
- [ ] **Linux outside CI**, so local verification runs where most CI does. Tried in a Debian 13 arm64 container (T108, `ci/linux/local_trial.sh`); next a physical machine and x86_64.
- [ ] **Verification fast enough for many agent loops a day.**
- [ ] **The review brief:** what changed since the last reviewed revision, and requirement coverage next to the evidence.
- [ ] **A study with reviewers** of whether the brief saves review time without missing defects. Until it is measured, OpenHarnX makes no claim that it does.

## Not planned

- Model calls in the gate. Verdicts come from checks that run, not from a model's opinion.
- An agent of its own, or orchestration of many agents (planning, delegation, parallel work). OpenHarnX checks the work of the agent you already use; `ohx bug` (experimental) drives that one agent through a single fix.
- A hosted service. OpenHarnX runs on your machine and in your CI.
