# Instructions for engineering agents

Practical rules for working in this repository. The product specifications live in the notes vault at `/Users/Shared/SecondBrain/02 Projects/OpenHarnX Research/`; start with its `AGENTS.md` and `PRD/README.md` before substantive work.

## Commands

```bash
uv sync               # install from uv.lock
./scripts/check.sh    # all required checks; must pass before a commit
uv run pytest         # tests only
uv run ohx doctor     # environment check
```

## Layers

Dependencies point inward only: interfaces (`cli`, hook) -> application services -> services -> `kernel` -> standard schemas.

- `openharnx.kernel` is **pure**: no I/O, clock, randomness or subprocesses. Time, IDs and inputs are passed in. Import-linter contracts in `pyproject.toml` enforce this; do not weaken them to make a check pass.
- Services perform I/O and call the kernel for every readiness, authority or policy decision.

## Invariants that code must preserve

- Evidence is bound to the exact candidate, checker, configuration and environment.
- A mandatory failed or unknown check blocks; no score, waiver or model output turns it into a pass.
- Readiness never grants authority to merge, deploy or publish.
- Missing costs, capabilities or evidence are shown as unknown, never as zero or success.
- History is append-only.

## Working rules

- Take one checklist task at a time. Record evidence in `docs/tasks/<task>.md`: commands, environment, results, limits.
- Add tests with behavior changes. Include negative cases for anything touching identity, gates, authority or persistence.
- Every new dependency is listed in `docs/dependencies.md` with version, license and purpose. Permissive licenses only (ADR-0002).
- Consequential design choices get an ADR in `docs/adr/`.
- Commits and all repository content must not attribute work to any AI system or assistant. No co-author trailers or generated-by notices.
- Write plain prose without em dashes.
