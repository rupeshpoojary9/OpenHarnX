# Instructions for engineering agents

Practical rules for working in this repository. The product specifications are kept in the owner's private notes ([ADR-0001](docs/adr/0001-source-location-and-spec-home.md)); on the owner's machine they are at `/Users/Shared/SecondBrain/02 Projects/OpenHarnX Research/`, so start there with its `AGENTS.md` and `PRD/README.md` before substantive work. Without them, the code, tests, `docs/adr/` and `docs/tasks/` carry the design.

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

**Every task is verified by OpenHarnX itself (dogfooding):**
1. Write the acceptance tests first, as a self-contained test file.
2. `ohx contract new --mode task --title ... --summary ... --acceptance tests/test_<task>.py --accept`. Project checks come from `ohx.toml`.
3. Implement until `ohx verify --sandbox srt` says READY.
4. Commit only on READY, with the candidate digest in the commit message. Any edit after verifying makes the report stale: verify again.

Run `ohx` from an **installed copy built from an earlier commit**, never from the working tree, so a change cannot alter the verifier that judges it.


- Take one checklist task at a time. Record evidence in `docs/tasks/<task>.md`: commands, environment, results, limits.
- Add tests with behavior changes. Include negative cases for anything touching identity, gates, authority or persistence.
- Every new dependency is listed in `docs/dependencies.md` with version, license and purpose. Permissive licenses only (ADR-0002).
- Consequential design choices get an ADR in `docs/adr/`.
- Commits and all repository content must not attribute work to any AI system or assistant. No co-author trailers or generated-by notices.
- Write plain prose without em dashes.
