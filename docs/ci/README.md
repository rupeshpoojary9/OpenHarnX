# Running the gate in any CI

`ohx gate` is a plain command. GitHub Actions (`.github/workflows/gate.yml`) is one wrapper; [`gitlab-ci.yml`](gitlab-ci.yml) and [`Jenkinsfile`](Jenkinsfile) are short examples for GitLab CI and Jenkins. Any other CI that runs a shell on Linux works the same way: make the base commit available, install a pinned OpenHarnX, run the gate, keep `ohx-gate/`. Exit code 0 is READY or NO REGRESSIONS; 10 is blocked, unknown or invalid. A gate without a contract has no acceptance tests, so a passing change is NO REGRESSIONS: nothing that passed on the base broke, and the change's own tests pass.

Both examples run the same block of commands, between `# ohx-gate commands` markers. `ci/linux/examples_probe.sh` runs that block on Linux under srt: a genuine change passing, a change that edits a test to match broken code BLOCKED, with and without the base branch in the checkout. That tests the commands, not GitLab or Jenkins themselves; real integrations wait for a pilot.

## What the runner needs

- Linux (or macOS) with git, Python 3.12, Node 20 or later, `srt` (sandbox-runtime 0.0.77), bubblewrap, socat and ripgrep. `ci/linux/Dockerfile` builds such an image.
- The sandbox creates user namespaces. On a virtual machine runner (a GitLab shell executor, a Jenkins agent on a VM) that works as is, except on Ubuntu 24.04, which needs `sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`. In a container it needs `--security-opt seccomp=unconfined --security-opt apparmor=unconfined --security-opt systempaths=unconfined`: the first two for user namespaces, the last because bubblewrap mounts `/proc`, which Docker masks. Shared container runners that do not allow these options cannot run the sandbox; the gate then reports every check unavailable, never READY.
- Windows runners are not supported.

## Trust rules

- **Install the gate from a pinned version you trust** (`OHX_VERSION` is a commit SHA, or a release once there are releases), never from the change under review.
- **The verdict comes from the base.** `ohx gate` reads the base commit's tests, `ohx.toml` and check configuration; nothing the change adds to them is used.
- **No secrets in the job.** The gate makes no model calls and needs no credentials; leave signing keys out (`OHX_SIGNING_KEY=none`).
- **Untrusted changes run on throwaway runners.** A merge request from a fork, or a pull request from someone outside the team, executes their code (tests, build steps) inside the sandbox. Use ephemeral runners, not a persistent shared agent. GitLab runs fork pipelines in the fork's project unless a maintainer starts one in the parent; Jenkins's GitHub Branch Source can take the Jenkinsfile from the target branch for untrusted contributors ("Trust" setting), which also stops a change from editing the pipeline that judges it.
- **Make the job a required check** (GitLab: "Pipelines must succeed"; Jenkins: a required status on the pull request) so a blocked change cannot be merged.

## Python projects

The locked run is `pytest` on the base's `tests/`. `pytest_args` in the base's `ohx.toml` adds the project's own options to it and to the default `tests` run, for example `pytest_args = ["-n", "auto"]` to run on every core with pytest-xdist (which must be in the protected environment). Per-test results still decide. A change to `pytest_args`, like any `ohx.toml` change, is caught by the weakening check (since baseline version 6; before it, the gate ignored the change's `ohx.toml` without flagging it).

## TypeScript and JavaScript projects

- **Do not run `npm ci` (or `npm install`) on the change before the gate.** It runs the change's install scripts in the job, outside the sandbox, and leaves a `node_modules` that is not part of what the gate judges. Put `environment = "npm"` in `ohx.toml` on the base branch instead: the gate installs from the base's `package-lock.json` itself, with `--ignore-scripts`, and a change that edits the lockfile gets no verdict until someone accepts a contract revision for it. The runner needs `npm` and network access for that install; the checks themselves run in the sandbox without network.
- **The runner** is `js_runner` in the base's `ohx.toml` (`vitest`, `jest` or `node`), else Vitest or Jest when the base's `package.json` lists it, else Node's own test runner. Node's runner reads TypeScript from Node 22.18; GitHub's Ubuntu runners ship an older Node, so add `actions/setup-node` (pinned to a commit) with `node-version: 22` or later before the gate.
- **Test files are locked wherever they are**: every `*.test.*`, `*.spec.*` and `__tests__/` file of the base runs against the change in place of the change's own copies.

## Go projects

- The gate runs `go test -json -count=1 ./...` when the base has `go.mod`, and locks every `_test.go` file of the base at its path. The runner needs Go (`actions/setup-go`, pinned to a commit). Fill the module cache before the gate (`go mod download` runs no module code); the checks then run in the sandbox without network.

## GitHub Actions in your own project

Use the action pinned to a commit. Pinning the action pins the gate: it installs itself from its own source, never from your code. Give the job a read-only token.

```yaml
name: OpenHarnX gate
on:
  pull_request:
    types: [opened, synchronize, reopened, labeled, unlabeled]
permissions:
  contents: read
  actions: read        # to tell which commit an approval label was given for
  pull-requests: read  # to read who added the label
jobs:
  gate:
    runs-on: ubuntu-24.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@<commit SHA>
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: rupeshpoojary9/OpenHarnX@<commit SHA of the OpenHarnX version you trust>
```

The action prepares the sandbox (bubblewrap, socat, ripgrep, srt 0.0.77, and Ubuntu 24.04's user-namespace setting), fetches the base if needed, runs `ohx gate --sandbox srt`, writes the report to the job summary, and sets the outputs `readiness` and `report`. Upload `${{ steps.<id>.outputs.report }}` with `actions/upload-artifact` to keep it. OpenHarnX's own `.github/workflows/gate.yml` uses the same action from the base checkout and adds a separate signing job.

## Approving intended test changes

The gate runs the base's tests against the change, so a change that rewrites or removes tests on purpose (a feature removed with its tests, a behaviour changed and its tests updated) is blocked. Replaying the gate over 29 agent pull requests of github/spec-kit, 7 of the 20 that were merged did this.

On GitHub a maintainer approves such a change by adding the `ohx-approve-tests` label (the action's `approve-tests-label` input; empty turns approvals off). The approval counts only when:

- whoever added the label last can push to the repository (write or admin);
- the label was added after the commit being judged was pushed. The gate checks this against GitHub's own record of workflow runs for the pull request, not commit dates, so a push after the label needs the label again (remove it and add it back).

Approved, the base's tests no longer bind. The change's own tests must pass, a test that passed on the base and still exists must still pass, and a new failing test still blocks. Removed tests and weakening findings are listed in the report as approved, with who approved and when. A refused label changes nothing and the report says why. The label is looked up with the job's read-only token, which reaches the gate process only, never the code under review.

## Approving on any platform: a signed approval

Without GitHub (GitLab, Jenkins, a plain git server), or as an alternative to the label, a maintainer signs the approval with their SSH key:

```sh
git fetch origin && git checkout <the change's head commit>
ohx approve-tests                          # signs "test changes approved for commit X"
git push origin refs/notes/ohx-approvals   # the signature travels as a git note
```

`ohx approve-tests` signs with the first of these it finds: the key named by `OHX_SIGNING_KEY` (a path; `none` turns signing off); git's own SSH signing key, when `gpg.format` is `ssh` and `user.signingkey` names a key file; else `~/.ssh/id_ed25519`, `~/.ssh/id_ecdsa` or `~/.ssh/id_rsa`. To check which key that is, compare `ssh-keygen -lf <key>.pub` with the fingerprint of the key listed below.

The gate accepts it when the signature verifies for exactly the judged commit and its key is listed in the base's `ohx.toml`:

```toml
approvers = [
  "rupesh ssh-ed25519 AAAAC3Nza...",
]
```

The list is read from the base only; a change that edits `ohx.toml` (approvers included) is a weakening finding, like any change to check configuration. A new push is a new commit and needs a new approval. Make the job fetch the notes before the gate (`git fetch origin "+refs/notes/ohx-approvals:refs/notes/ohx-approvals"`; the GitHub Action does this), or pass a signature written with `ohx approve-tests --out approval.sig` as `ohx gate --approval-file approval.sig`. Approval signatures use their own namespace, so an evidence signature cannot stand in for one.
