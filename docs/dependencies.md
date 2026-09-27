# Dependency inventory

Policy: [ADR-0002](adr/0002-dependency-policy.md). Versions are those resolved in `uv.lock` on 2026-09-27. Licenses were read from installed package metadata (license expression or classifiers), not from memory.

## Runtime dependencies

None. The `ohx` package currently depends only on the Python standard library.

## Build backend (not shipped)

| Package | Version | License | Purpose |
|---|---|---|---|
| hatchling | 1.32.4 (requirement `>=1.26`) | MIT | Build backend |
| packaging | 25.0 | Apache-2.0 OR BSD-2-Clause | Hatchling dependency |
| pathspec | 1.1.1 | MPL-2.0 | Hatchling dependency |
| pluggy | 1.6.0 | MIT | Hatchling dependency |
| trove-classifiers | 2025.12.1.14 | Apache-2.0 | Hatchling dependency |

## Development tools (not shipped)

Direct:

| Package | Version | License | Purpose |
|---|---|---|---|
| pytest | 9.1.1 | MIT | Tests |
| hypothesis | 6.168.2 | MPL-2.0 | Property-based tests |
| ruff | 0.16.9 | MIT | Format and lint |
| mypy | 2.3.1 | MIT | Strict type checking |
| import-linter | 2.15 | BSD-2-Clause | Layer and kernel-purity contracts |

Transitive:

| Package | Version | License |
|---|---|---|
| ast_serialize | 0.11.2 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| grimp | 3.17 | BSD-2-Clause |
| iniconfig | 2.3.0 | MIT |
| librt | 0.15.0 | MIT |
| markdown-it-py | 4.2.0 | MIT |
| mdurl | 0.1.2 | MIT |
| mypy_extensions | 1.1.0 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pathspec | 1.1.1 | MPL-2.0 |
| pluggy | 1.6.0 | MIT |
| pygments | 2.21.0 | BSD-2-Clause |
| rich | 15.0.0 | MIT |
| sortedcontainers | 2.4.0 | Apache-2.0 |
| typing_extensions | 4.16.0 | PSF-2.0 |

## License notes

Two packages, `hypothesis` and `pathspec`, are MPL-2.0, a weak file-level copyleft license. Both are development or build tools. Neither is imported by, linked into or distributed with OpenHarnX. ADR-0002 records how this is treated, pending owner confirmation.
