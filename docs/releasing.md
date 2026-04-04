# Releasing Captain Search

This repository is set up for low-maintenance PyPI publishing with `uv`, Hatchling, and PyPI Trusted Publishing from GitHub Actions.

## One-time setup

1. Confirm that the `captain-search` project name is acceptable on PyPI.
2. In PyPI, create a pending Trusted Publisher for project `captain-search` that points at this GitHub repository and `.github/workflows/publish.yml`.
3. Keep the publish workflow filename and the `pypi` environment name stable after registering them with PyPI.
4. In GitHub, create an environment named `pypi` if you want explicit environment settings before the first release.
5. The first successful trusted-publishing run creates the PyPI project if it does not exist yet.

## Normal release flow

1. Validate the repo.

```bash
uv run --extra dev python -m pytest -q
uv run --extra dev python -m ruff check src tests
```

2. Bump the package version.

```bash
uv version --bump patch
# or: uv version --bump minor
# or: uv version --bump major
```

3. Build locally if you want a final sanity check.

```bash
uv build --no-sources
```

4. Commit the version bump and tag the release.

```bash
git add pyproject.toml uv.lock
git commit -m "Release v$(uv version --short)"
git tag v$(uv version --short)
git push origin main --tags
```

5. GitHub Actions builds the distributions and publishes them to PyPI through Trusted Publishing.

## Optional first-release dry run

If you want one manual rehearsal before the first real release, publish once to TestPyPI.

```bash
uv build --no-sources
uv publish --index testpypi
```

Then verify installation without using the local checkout:

```bash
uv run --with captain-search --no-project -- python -c "import captain_search"
```

## User-facing install commands after release

```bash
uv tool install captain-search
uvx --from captain-search csearch --help
uvx --from captain-search csearch web "openai api"
uvx --from captain-search csearch mcp --help
```

## Notes

1. The PyPI distribution name is `captain-search`.
2. The import package remains `captain_search`.
3. The short CLI alias `csearch` is installed from the `captain-search` package, so the correct one-off form is `uvx --from captain-search csearch ...`.
4. The MCP server now requires an explicit `mcp` subcommand.