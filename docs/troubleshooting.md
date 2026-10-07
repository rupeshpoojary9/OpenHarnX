# Troubleshooting

Start with `ohx doctor`. It checks Python, git, the sandbox (`srt`) and Node, the sandbox's helpers on Linux, whether `ohx.toml` reads, and which interpreter the checks will use and whether it has pytest, and prints the command that fixes each problem.

Each entry below starts with what you see, then why, then what to do. If yours is not here, open an issue with `ohx report --json`, or a [trial report](https://github.com/rupeshpoojary9/OpenHarnX/issues/new?template=trial-report.yml).

## Installing

**`ohx: command not found` after `uv tool install openharnx`.** uv puts tools in a folder that is not on your `PATH` yet. Run `uv tool update-shell`, then open a new terminal.

**`ohx doctor` warns `srt: the sandbox is not installed`.** Checks still run, but without isolation, and every report says so ("checkers ran without isolation, so tampering is detected, not prevented"). Install the sandbox with `npm install -g @anthropic-ai/sandbox-runtime@0.0.77`; it needs Node 20 or later.

**On Linux the sandbox will not start ("the srt sandbox did not start the checker").** The sandbox needs bubblewrap, socat and ripgrep (`apt install bubblewrap socat ripgrep`) and user namespaces. On Ubuntu 24.04 run `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`. In a container it needs `--security-opt seccomp=unconfined --security-opt apparmor=unconfined --security-opt systempaths=unconfined`. Local Linux is not yet a supported platform for 0.1.x; Linux in CI is ([docs/ci](ci/README.md)).

## Locking the tests

**`ohx init --lock-tests` stops with `the 'tests' suite could not run (crash): ... No module named pytest` and `checks run with ...`.** The checks run with an interpreter that does not have your project's test dependencies. OpenHarnX uses `python` from `ohx.toml` if you set it, else the project's `.venv` or `venv`, else the active virtual environment, else its own interpreter, which has no pytest. Put the right one in `ohx.toml`:

```toml
python = ".venv/bin/python"
```

then run `ohx init --lock-tests` again. With a `uv.lock`, `environment = "uv"` builds a protected environment from it instead.

**`ohx: locked anyway: a later run counts once every test passes`.** Some of your tests could not run when they were locked, usually because they import code the task has not written yet. That is expected for tests written first; they count once the whole suite passes.

## Verifying

**Every check is UNKNOWN or INVALID with "the checker interpreter's environment changed since the contract was accepted".** Something in the interpreter's environment changed after you locked: a package installed or upgraded, a `.pth` file added. The note names the files. If you changed it on purpose, lock again (`ohx init --lock-tests`, or `ohx contract accept <file>` for a contract you wrote), or use `environment = "uv"`, which this check does not need.

**Every check is INVALID with "uv.lock changed since contract acceptance; accept a contract revision".** With `environment = "uv"`, the dependencies are part of the contract. Accept the new lockfile on purpose: `ohx contract accept <file>`, or `ohx init --lock-tests` again. A change to your own project's version alone does not count.

**`OpenHarnX report: STALE` ("subject_changed: the repository differs from the verified candidate").** You, or the agent, changed files after the last verification; the report lists them. Run `ohx verify` again.

**BLOCKED because you changed a test on purpose.** The locked tests are the point, so an intended change needs an explicit decision. Locally, lock again after reviewing the change: `ohx init --lock-tests`. In CI, a maintainer approves it: the `ohx-approve-tests` label on GitHub, or a signed `ohx approve-tests` on any platform ([how](ci/README.md#approving-on-any-platform-a-signed-approval)).

**NO REGRESSIONS when you expected READY.** READY needs acceptance tests agreed for the task; without them OpenHarnX can only say that nothing which passed before broke. Agree them first: `ohx contract new --title ... --summary ... --acceptance tests/test_task.py --accept`.

**INVALID with "candidate changed during verification".** Files changed while the checks ran, often an agent or an editor still writing. Wait for it to finish, then verify again.

**INVALID with "the check ran other code than the candidate's".** The checker environment holds another copy of your project, usually an editable install of a different checkout, so the tests ran that copy. Build the environment without the project, or from this checkout.

## Claude Code

**No verdict in `claude -p` output.** Plain `--output-format json` carries no hook output. Use `--output-format stream-json --verbose`, where the verdict appears as `Stop says: OpenHarnX: ...`, or run `ohx report` afterwards.

**The hook does not run, or runs with the wrong store.** Run `ohx hook install` in the repository. If you set `OHX_HOME`, export it before starting Claude Code, since the hook inherits Claude Code's environment.

## CI

**The gate job times out.** The suite runs up to three times under the sandbox (the base's tests at acceptance, the same tests against the change, and the change's own tests), and on a CI runner it can be several times slower than on your machine. Run it in parallel (`pytest_args = ["-n", "auto"]` in the base's `ohx.toml`, with pytest-xdist in the environment), give each suite more time (`suite_timeout_s`, 300 seconds unless set), and raise the job's `timeout-minutes`.

**An approval signature is not found (GitLab, Jenkins).** The signature travels as a git note, which a default fetch does not bring. Fetch it before the gate: `git fetch origin "+refs/notes/ohx-approvals:refs/notes/ohx-approvals"`.

**The approval label does not count.** It counts only when the person who added it last can push to the repository, and only when it was added after the commit being judged was pushed. After a new push, remove the label and add it again.
