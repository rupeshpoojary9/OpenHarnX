<p align="center"><img src="docs/assets/openharnx-logo.png" alt="OpenHarnX" width="600"></p>

# OpenHarnX

OpenHarnX is a local-first delivery system that plans, staffs, controls and verifies work done by existing coding agents such as Claude Code and Codex, and learns which team configurations actually work.

## Status

**Early bootstrap. Nothing product-facing works yet.** This repository currently contains only the build, test and packaging foundation (task T02) and an `ohx doctor` command that checks the local environment. Evidence capture, gates, reports, teams and every other capability described in the specifications are planned, not implemented.

## Specifications

The research, product requirements, architecture and roadmap live outside this repository, in the project owner's notes vault:

- Research index: `02 Projects/OpenHarnX Research/00 Read This First.md`
- Product requirements: `02 Projects/OpenHarnX Research/PRD/`
- Architecture: `02 Projects/OpenHarnX Research/Design/Architecture.md`
- Roadmap and task checklist: `02 Projects/OpenHarnX Research/PRD/ROADMAP.md` and `CHECKLIST.md`

Implementation decisions for this code base are recorded in [`docs/adr/`](docs/adr/). See [ADR-0001](docs/adr/0001-source-location-and-spec-home.md) for why the specifications and code live apart.

## Development setup

Requires Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and git.

```bash
uv sync                 # create the environment from uv.lock
./scripts/check.sh      # format, lint, strict types, layer rules, tests
uv run ohx doctor       # check the local environment
```

Install the command for local use, and remove it again:

```bash
uv tool install .
ohx --version
uv tool uninstall openharnx
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success or ready |
| 10 | Valid result that is blocked, unknown or failing a required check |
| 2 | Usage or input error |
| 1 | Internal failure |

## License

Apache-2.0. See [LICENSE](LICENSE). Dependencies and their licenses are listed in [docs/dependencies.md](docs/dependencies.md).
