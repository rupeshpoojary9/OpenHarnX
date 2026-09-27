# ADR-0005: Candidate identity and canonicalization

- Date: 2026-09-27
- Owner: Rupesh Poojary
- Status: accepted for M1
- References: vault ADR-05; PRD 04 STATE-03, STATE-04, STATE-08; OHX-003; Architecture §7; task T03 part B; spike `spikes/candidate_identity/`

## Context

Evidence must bind to the exact code that was verified. `HEAD` is not enough: agents leave uncommitted edits and new untracked files. The identity must also stay stable when nothing relevant changed, including when OpenHarnX writes its own reports.

## Decision

The candidate is identified by a manifest built from git plumbing, read-only:

- **File set:** `git ls-files --cached --others --exclude-standard`. That covers tracked, modified and untracked-but-not-ignored files.
- **Per entry:**
  - the normalized relative path (POSIX separators, Unicode NFC)
  - the type: file, symlink, deleted or other
  - for files, the executable bit and SHA-256 of the content
  - for symlinks, the link target as text, never followed
- **Excluded:** OpenHarnX's own output directory. Ignored files are **counted and reported** (`ignored_present`) but not hashed. They are a visible limitation, not a silent one.
- **Digest:** SHA-256 over canonical JSON of the manifest version, algorithm and entries.
- **Aliases, not identity:** the base commit is recorded but excluded from the digest. Committing unchanged content keeps the same identity.
- **Speed:** a stat cache keyed on path, size, modification time, inode and mode avoids rehashing unchanged files.
- **Verification binding:** the manifest is recomputed after verification. A difference marks the run invalid. For M1 this before-and-after comparison is the default. Materialized snapshots come in when the verifier boundary needs them (ADR-07).

## Evidence

**Tests:** 15 of 15 fixture tests pass (`spikes/candidate_identity/test_manifest.py`). They cover:
- determinism
- dirty tracked edit
- untracked source
- ignored file (unchanged, but reported)
- excluded output
- executable bit
- symlink not followed
- rename
- case-only rename on macOS
- deleted tracked file
- commit of the same content
- mutation during verification
- read-only inspection (git status and file mtimes unchanged)
- stat cache reuse and edit detection

**Mutation checks** show the tests can fail when the implementation is wrong:

| Mutation | Result |
|---|---|
| Ignoring untracked files | 3 tests fail |
| Dropping the executable bit | 1 test fails |
| Folding the commit into the digest | 1 test fails |

**Performance** on this Mac (2026-09-27, warm filesystem):

| Repository | Files | Size | Cold build | Warm build | Python copy of snapshot |
|---|---|---|---|---|---|
| Fixture service | 4 | under 0.1 MB | 0.04 s | 0.04 s | under 0.01 s |
| Owner's vault (read only) | 9,486 | 1,133.5 MB | 2.41 s | 0.17 s | 3.76 s |

The vault run reported 921 ignored files and left the repository status unchanged. Per-file APFS clone through a `cp -c` subprocess took 26.11 s, dominated by process start-up rather than cloning. A native clone call remains an optimization to test if snapshot materialization becomes a bottleneck.

## Consequences

- Warm fingerprinting is well inside the stack research trigger (hashing above 2 s after caching). The cold build of about 2.4 s for a 1.1 GB tree is acceptable because it runs once per session.
- Ignored files that affect a build (for example `.env`) are not in the identity. Profiles can declare specific ignored paths to include; until then the count is shown in the report.

## Open items

- Git submodules: not tested; declared unsupported for M1.
- Unicode normalization differences on case-sensitive filesystems: not tested beyond NFC normalization.
- Dependency lockfile and environment digests belong to the environment descriptor (T09), not this manifest.
