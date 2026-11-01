# Release Rules
<!-- last-analyzed: 2026-11-01T00:00:00+08:00 -->

## Version Sources
- `pyproject.toml`: `[project] version`
- `unipus_web/__init__.py`: `__version__`
- `unipus_web/config.py`: `VERSION`

The three values must stay identical. Update them together before tagging.

## Release Trigger
Manual release from a `release/vX.Y.Z` branch. Tag as annotated `vX.Y.Z` after the test gate and Windows EXE build pass.

## Test Gate
- Local: `.venv\Scripts\python.exe -m pytest`
- CI: none in this repository.

## Registry / Distribution
No registry publication. Distribute the PyInstaller artifact `dist/UnipusHelper.exe` through a GitHub Release attached to the tag.

## Release Notes Strategy
Use `CHANGELOG.md` with Keep a Changelog-style sections. Write the user-visible changes for the release before committing and tagging.

## CI Workflow Files
None.

## First-Time Setup Gaps
- No release workflow exists yet.
- Git had no tags before `v2.0.1`.
- `dist/` and `build/` were added to `.gitignore` for this release because the project now creates local build artifacts.