# ADR-0003: Implementation language and packaging

- Date: 2026-09-27
- Owner: Rupesh Poojary
- Status: accepted
- References: vault ADR-03; [Stack research](/Users/Shared/SecondBrain/02%20Projects/OpenHarnX%20Research/10%20Stack%20Research.md); task T02

## Context

The owner chose Python 3.12+ with uv on 2026-09-27, based on the stack research. The decision register requires a working minimal CLI plus a test and packaging spike compared against one credible alternative. TypeScript on Node was the alternative, being closest to the Claude Code ecosystem.

## Spike

The same tiny CLI (`ohx --version`, `ohx doctor` checking the runtime and git, exit codes 0, 2 and 10) was built both ways. Measured on the owner's Mac (arm64, macOS 26.5.2), 2026-09-27, informal timings with warm caches:

| Measure | Python 3.12.7 + uv 0.8.14 | TypeScript + Node 24.13.1 |
|---|---|---|
| Runtime dependencies | 0 | 0 |
| Development environment | 21 packages, 113 MB (pytest, hypothesis, ruff, mypy, import-linter) | 3 packages, 26 MB (typescript, types) |
| Checks available | Format, lint, strict types, import-layer contracts, tests | Strict types, tests |
| Test run | 8 tests in 0.54 s | 2 tests in 0.22 s |
| Type check or build | Included in `check.sh` | 1.22 s |
| Isolated install | `uv tool install .` in 0.25 s | `npm install -g` of a packed tarball in 0.17 s |
| Installed startup | 0.04 s | 0.02 to 0.03 s |
| Clean uninstall | Yes | Yes |

The Python development environment is larger because it carries more tooling, most visibly the layer contracts that enforce kernel purity. TypeScript has no equivalent configured in this spike.

## Decision

Python 3.12+ with uv, the hatchling build backend and a committed `uv.lock`. Distributed as a normal Python package, installed with `uv tool install` or pipx. The CLI uses standard-library `argparse` for now; adopting Typer and Rich is deferred to the CLI workflow task (T11).

## Rationale

- The spike found no blocker. Startup differs by about 10 to 20 ms, which is small against hook timeouts measured in seconds.
- The deciding factors are the ones in the stack research: the evaluation and statistics ecosystem needed for pilots and calibration, and owner fluency.
- The TypeScript spike was fast and small but offers no advantage that changes the decision.

## Limits of the spike

The spike did not test any of the following:
- Claude Code hook integration (ADR-06)
- storage (ADR-04)
- sandboxing (ADR-07)
- Linux or Windows
- a larger codebase

## Revisit triggers

From the stack research:
- hook p95 above 100 ms in real sessions
- candidate hashing above 2 s on representative repositories after caching
- a need to embed the core in a non-Python host
- the M5 independent implementation
