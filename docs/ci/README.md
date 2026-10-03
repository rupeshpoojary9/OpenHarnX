# Running the gate in any CI

`ohx gate` is a plain command. GitHub Actions (`.github/workflows/gate.yml`) is one wrapper; [`gitlab-ci.yml`](gitlab-ci.yml) and [`Jenkinsfile`](Jenkinsfile) are short examples for GitLab CI and Jenkins. Any other CI that runs a shell on Linux works the same way: make the base commit available, install a pinned OpenHarnX, run the gate, keep `ohx-gate/`. Exit code 0 is READY; 10 is blocked, unknown or invalid.

Both examples run the same block of commands, between `# ohx-gate commands` markers. `ci/linux/examples_probe.sh` runs that block on Linux under srt: a genuine change READY, a change that edits a test to match broken code BLOCKED, with and without the base branch in the checkout. That tests the commands, not GitLab or Jenkins themselves; real integrations wait for a pilot.

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

## TypeScript and JavaScript projects

- **Do not run `npm ci` (or `npm install`) on the change before the gate.** It runs the change's install scripts in the job, outside the sandbox, and leaves a `node_modules` that is not part of what the gate judges. Put `environment = "npm"` in `ohx.toml` on the base branch instead: the gate installs from the base's `package-lock.json` itself, with `--ignore-scripts`, and a change that edits the lockfile gets no verdict until someone accepts a contract revision for it. The runner needs `npm` and network access for that install; the checks themselves run in the sandbox without network.
- **The runner** is `js_runner` in the base's `ohx.toml` (`vitest`, `jest` or `node`), else Vitest or Jest when the base's `package.json` lists it, else Node's own test runner. Node's runner reads TypeScript from Node 22.18; GitHub's Ubuntu runners ship an older Node, so add `actions/setup-node` (pinned to a commit) with `node-version: 22` or later before the gate.
- **Test files are locked wherever they are**: every `*.test.*`, `*.spec.*` and `__tests__/` file of the base runs against the change in place of the change's own copies.

## GitHub Actions in your own project

Use the action pinned to a commit. Pinning the action pins the gate: it installs itself from its own source, never from your code. Give the job a read-only token.

```yaml
name: OpenHarnX gate
on:
  pull_request:
permissions:
  contents: read
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
