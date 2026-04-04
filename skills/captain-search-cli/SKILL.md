---
name: captain-search-cli
description: Use Captain Search from the terminal when the user needs exact csearch or captain-search commands, checkout-based CLI usage, future PyPI-installed CLI usage, smoke tests, provider selection, repo-scoped code search, webpage fetches, JSON output, or shell-friendly troubleshooting. Prefer this skill for direct CLI workflows from a checkout or installed package. Do not use it for MCP client or server setup unless the user explicitly asks for MCP installation.
---

# Captain Search CLI

Use this skill for direct terminal work with Captain Search.

## Resolve the entrypoint

1. If you are inside a checkout of this repository, prefer `uv run csearch ...`.
2. If the project virtualenv is already active and `csearch` resolves, `csearch ...` is acceptable.
3. Outside the repo root, use `uv run --directory /path/to/captain-search csearch ...`.
4. Only use published-package entrypoints such as `uvx --from captain-search csearch ...` or `uv tool install captain-search` after a public package release exists.
5. If the user wants the public-install path or asks why `uvx csearch` is wrong, explain that `csearch` is a script exposed by the `captain-search` package, so the correct one-off form is `uvx --from captain-search csearch ...`.
6. If the user wants a reusable agent install from this checkout, use `uv run csearch skill install --scope user`. After a public release exists, prefer `uvx --from captain-search csearch skill install`.

## Pick the workflow

1. For first-run install, auth, smoke tests, or a recommended setup path, read `references/onboarding.md`.
2. For exact command construction, formats, and subcommand rules, read `references/commands.md`.
3. For provider trouble, empty results, or rate limits, run `uv run csearch doctor` from the checkout before assuming a backend is broken.

## Non-negotiable CLI rules

1. Use the short subcommands: `web`, `code`, `fetch`, `doctor`, `skill`, `mcp`, `version`.
2. Do not use legacy `search-web`, `search-code`, `fetch-webpage`, or `serve` examples.
3. Bare `csearch` or `captain-search` prints help and exits `0`. Use `mcp` explicitly for server mode.
4. Use `web --all` for breadth. Do not use `--provider multi` or `--provider all`.
5. `web`, `code`, and `fetch` all support `--format json`.
6. Treat exit code `0` as top-level success only. Provider-level warnings or partial failures can still appear in the output.
7. Keep install guidance honest: do not present `uv tool install captain-search` or `uvx --from captain-search ...` as currently available unless the package has actually been published.

## Route quickly

- Live web results or provider fan-out: use `web`.
- Repository-aware code lookup: use `code`.
- HTML, GitHub blob URLs, PDFs, or docs extraction: use `fetch`.
- Provider health and cooldown inspection: use `doctor`.
- MCP server launch: use `mcp`.

## Minimal examples

```bash
uv run csearch skill install --scope user
uv run csearch web "openai api" --max-results 5
uv run csearch code "search_web" --repo mnm-matin/captain-search --format json
uv run csearch fetch https://example.com --format json
uv run csearch doctor
uv run csearch mcp --transport stdio
```