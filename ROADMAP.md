# Roadmap

Where OpenHarnX is going next. No dates: work is taken in order and shipped when it is verified. Priorities move with what users report, so if something here matters to you, or something missing does, open an issue.

What is released and supported today is in the [README](https://github.com/rupeshpoojary9/OpenHarnX#supported-in-011) and [docs/gate-release-criteria.md](docs/gate-release-criteria.md).

## Next (0.1.x)

- **Code that detects the test runner.** Flag changed code that behaves differently when pytest is running (for example by checking `sys.modules` or `PYTEST_CURRENT_TEST`), a way for a change to pass every test and fail in use.
- **Approval and CI documentation.** The GitLab example fetching approval notes, which SSH key `ohx approve-tests` signs with, and a BLOCKED report that says how test changes are approved.
- **The checker's interpreter.** Also fingerprint folders that a `.pth` file in its environment points to.
- **Faster CI.** The gate runs the whole suite up to three times under the sandbox; reuse what can be reused.
- **`ohx doctor`** checks the sandbox and JavaScript setups, not only Python and git.

## Being considered (0.2)

- **TypeScript, JavaScript and Go as supported**, not experimental, including pnpm and Yarn lockfiles.
- **Linux outside CI**, so local verification runs where most CI does.
- **Verification fast enough for many agent loops a day.**
- **The review brief:** what changed since the last reviewed revision, and requirement coverage next to the evidence.
- **A study with reviewers** of whether the brief saves review time without missing defects. Until it is measured, OpenHarnX makes no claim that it does.

## Not planned

- Model calls in the gate. Verdicts come from checks that run, not from a model's opinion.
- An agent of its own, or orchestration of many agents (planning, delegation, parallel work). OpenHarnX checks the work of the agent you already use; `ohx bug` (experimental) drives that one agent through a single fix.
- A hosted service. OpenHarnX runs on your machine and in your CI.
