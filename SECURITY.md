# Security

OpenHarnX is a gate: its job is to stop a change that games its tests. A way around it, such as a change that reaches READY when it should not, a check that runs outside the sandbox, or code under review that reads a runner's secrets, is a vulnerability.

## Reporting a vulnerability

Please report it privately, not in a public issue or pull request, so it can be fixed before it is known.

Use GitHub's private vulnerability reporting: on the repository's **Security** tab, choose **Report a vulnerability** (or open `https://github.com/rupeshpoojary9/OpenHarnX/security/advisories/new`). Only the maintainer sees the report, and the fix is discussed there.

Useful to include: the OpenHarnX commit or release, the platform and sandbox (`ohx doctor` prints both), the steps or a small repository that shows it, and what you expected the verdict to be.

This is a one-person project. Reports are answered as soon as possible; a confirmed issue is fixed in a new release, and the advisory credits you unless you prefer otherwise.

## Scope

What OpenHarnX claims, and what it does not, is in [docs/threat-model.md](docs/threat-model.md) (section "The gate" for the public gate) and [docs/gate-release-criteria.md](docs/gate-release-criteria.md). A way around a claim marked prevented or detected is in scope. Items listed there as open or out of scope are known; a new way to exploit one is still welcome.

## Supported versions

Only the latest release receives fixes.
