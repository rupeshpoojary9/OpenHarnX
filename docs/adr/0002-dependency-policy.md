# ADR-0002: Meaning of "built in-house" and dependency policy

- Date: 2026-09-27
- Owner: Rupesh Poojary
- Status: accepted (core rule and clause 3, owner decisions 2026-09-27)
- References: vault ADR-02; PRD 00 PROD-11; PRD 18 RELEASE-02; [inventory](../dependencies.md)

## Decision

1. **Original logic.** OpenHarnX's own product logic is original work: contracts, evidence, identity, gates, policy, planning, ledger, recovery and learning.
2. **Runtime dependencies.** Plumbing libraries may be used at runtime if their license is permissive: MIT, BSD, Apache-2.0, ISC or PSF. Each must be listed in `docs/dependencies.md` with version, license and purpose before use.
3. **Development and build tools.** Tools that are not imported by, linked into or shipped with OpenHarnX may also use weak file-level copyleft licenses such as MPL-2.0. Strong copyleft (GPL, AGPL) is not allowed anywhere without an explicit owner decision.
4. **No reimplementation of solved infrastructure.** Do not write new cryptography, storage engines or test frameworks to satisfy "in-house".

## Why clause 3 is needed

The T02 inventory found two MPL-2.0 packages, both outside the shipped product:
- `hypothesis`, a direct development dependency used for property-based tests. The Core Standard calls for property testing.
- `pathspec`, pulled in by the build backend and the lint stack.

Clause 3 permits them. The owner approved clause 3 on 2026-09-27.

## Consequences

- The runtime dependency list is currently empty.
- Every dependency change updates the inventory in the same commit.
- Release packaging (T46) must produce an SBOM and license report consistent with this policy.
