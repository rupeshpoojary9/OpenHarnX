# ADR-0001: Source location and specification home

- Date: 2026-09-27
- Owner: Rupesh Poojary
- Status: accepted (location); proposed (spec home, revisit after the M1 TDD)
- References: vault decision register ADR-01; task T02

## Context

The OpenHarnX research, PRDs and architecture were written in the owner's notes vault (`/Users/Shared/SecondBrain/02 Projects/OpenHarnX Research/`). The PRD pack requires the implementation to live outside the vault and requires one canonical home for each specification, never two editable copies.

## Options

1. Move all specifications into this repository now.
2. Keep specifications in the vault and implementation records in this repository, linked both ways.
3. Keep everything in the vault, including code.

## Decision

- Code lives at `/Users/Shared/OpenHarnX`, a local git repository with no remote until the owner decides otherwise. The owner chose `/Users/Shared` as the home of his standard development suite.
- Research, PRDs, the architecture and future milestone TDDs stay canonical in the vault for now (option 2).
- Implementation ADRs, task evidence records and the dependency inventory live in this repository under `docs/`. The vault decision register links to them.

## Consequences

- No document exists in two editable places.
- An agent working here must read the vault specifications by path; `AGENTS.md` and `README.md` point to them.
- A public release later will need the specifications moved or published alongside the code.

## Revisit trigger

Acceptance of the M1 TDD, or a decision to publish the repository.
