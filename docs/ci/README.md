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
