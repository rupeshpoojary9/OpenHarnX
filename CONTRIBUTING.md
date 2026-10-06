# Contributing to OpenHarnX

Thanks for looking. OpenHarnX is an early project with one maintainer, so issues and small, focused pull requests help most.

## Reporting problems

- **A wrong verdict is the most useful report.** If OpenHarnX said READY or NO REGRESSIONS for a change that was broken, or BLOCKED a change that was fine, open an issue with the report (`ohx report --json`), what the change did and, if you can, a small repository that reproduces it.
- Bugs, confusing output and documentation gaps are welcome as issues too. Say which version (`ohx --version`), platform and test runner you used.
- **Security problems go through private vulnerability reporting, not a public issue.** See [SECURITY.md](SECURITY.md).

For anything larger than a small fix, open an issue first so we can agree on the approach before you spend time on it.

## Setting up

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and git. For sandboxed runs, Node 20 or later and `srt` (`npm install -g @anthropic-ai/sandbox-runtime@0.0.77`).

```bash
uv sync                 # the environment from uv.lock
./scripts/check.sh      # format, lint, strict types, layer rules, tests; must pass
uv run ohx doctor       # the local environment
```

## How a change is verified here

OpenHarnX checks its own changes. Each one starts with its acceptance tests, written before the code, in a self-contained file under `tests/`. The maintainer then locks them with `ohx contract new --acceptance tests/test_<change>.py --accept`, makes the change, and commits only when `ohx verify --sandbox srt` says READY, using an `ohx` installed from an earlier commit, never the working tree. The commit message names the contract and the candidate digest.

You do not need to do the locking yourself. Write the tests and the change, run `./scripts/check.sh`, and open a pull request. The OpenHarnX gate then runs in CI:

- The base branch's tests run as locked copies against your change; a test that passed on the base must still pass.
- Editing, skipping or deleting an existing test, or loosening check configuration, is blocked unless a maintainer approves it with the `ohx-approve-tests` label. If your change needs that, say why in the pull request.
- Changes to `.github/`, `action.yml` and the workflow guard tests need the code owner's review.
- Workflows from outside contributors start only after a maintainer approves the run.

The gate takes about 10 to 30 minutes, because the suite runs under the sandbox.

## Code rules

The full list is in [AGENTS.md](AGENTS.md); the ones that matter most:

- Dependencies point inward: interfaces, application services, services, `kernel`. The kernel stays pure (no I/O, clock, randomness or subprocesses); import-linter enforces it.
- A mandatory check that fails or is unknown blocks; nothing turns it into a pass. Readiness never authorizes a merge or a deploy. Missing costs and evidence are shown as unknown, never as zero.
- Every behaviour change comes with tests, including negative cases for anything touching identity, gates, authority or persistence.
- A new dependency goes in [docs/dependencies.md](docs/dependencies.md) with its version, license and purpose. Permissive licenses only.
- Consequential design choices get an ADR in [docs/adr/](docs/adr/); a task's evidence goes in [docs/tasks/](docs/tasks/).
- Plain, direct prose in docs and messages.

## License

OpenHarnX is licensed under Apache-2.0. Unless you say otherwise, a contribution you submit is licensed under the same terms (section 5 of the [license](LICENSE)).
