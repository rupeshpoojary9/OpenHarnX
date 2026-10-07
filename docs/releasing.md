# Releasing

A release is a git tag on a commit of `main` that was verified READY under srt (its commit message names the contract and candidate digest) and whose CI gate passed. Releases are made by the owner; nothing here publishes on its own.

1. Pick the commit. It must be on `main`, verified READY, with the GitHub Actions gate green.
2. Set `version` in `pyproject.toml` to the release number (`0.1.0` for the first), verify READY and commit.
3. Tag that commit with an annotated, signed tag: `git tag -s v0.1.0 -m "OpenHarnX 0.1.0"`, then `git push origin v0.1.0`.
4. Create the GitHub release from the tag. Its notes name the full commit SHA, the changes and the release criteria met.
5. Publishing the release starts `.github/workflows/publish.yml` (from 0.1.1). Its build job refuses a version that does not match the tag and builds the wheel and source distribution with `uv build`; its upload job waits in the `pypi` environment until the owner approves it on the run's page, then uploads to PyPI through trusted publishing (no token is stored; PyPI trusts this workflow by name, and signs attestations of the files). The `pypi` environment accepts only `v*` tags.
6. Install the published version in a fresh environment (`uv tool install openharnx==<version>`) and run the cheat demo before announcing it.

## Installing a release

```bash
uv tool install git+https://github.com/rupeshpoojary9/OpenHarnX@v0.1.0
ohx --version
```

A tag can be moved; a commit cannot. Where it matters, such as in CI, install by the commit SHA from the release notes (`@<sha>`) and keep it in the workflow, as `OHX_VERSION` does in `docs/ci/`. `git ls-remote https://github.com/rupeshpoojary9/OpenHarnX v0.1.0` shows which commit a tag points to.
