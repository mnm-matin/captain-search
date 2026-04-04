# Captain Search Commands

Use this reference when you need an exact command instead of a high-level explanation.

## Entry points

1. From this repository, prefer `uv run csearch ...`.
2. Outside the repo root, use `uv run --directory /path/to/captain-search csearch ...`.
3. If the virtualenv is already active, `csearch ...` is fine.
4. `captain-search ...` is equivalent when the longer name is acceptable.
5. Only use `uvx --from captain-search csearch ...` or `uv tool install captain-search` after a package release exists.
6. Use `uv run csearch skill install --scope user` when the user wants a reusable agent skill from this checkout.

## web

1. Use `web` for live web results.
2. Omit `--provider` to use `auto`.
3. Use `--all` to query all enabled providers in parallel.
4. Use a comma-separated `--provider` list to run a specific set of providers.
5. Valid provider names are `serper`, `brave`, `tavily`, `perplexity`, `parallel`, `exa`, and `exa_mcp`.
6. `--all` and `--provider` are mutually exclusive.
7. `--max-results` accepts `1-50`.
8. `--format` accepts `markdown` or `json`.
9. Unknown providers can appear as warnings if at least one valid provider succeeds. If nothing valid remains, the command returns a top-level error.
10. Auto and multi-provider output is deduplicated and capped to the overall `--max-results`.

Examples:

```bash
uv run csearch web "openai api" --provider brave --format json
uv run csearch web "python site:docs.python.org asyncio" --max-results 8
uv run csearch web "react server actions" --all --max-results 10
```

## code

1. Add `--repo` whenever repository scope matters.
2. Pass `--repo` as `owner/repo`, a Git URL, a local path, or a `file://` local path.
3. Remote repositories are cloned or refreshed under `~/.cache/captain-search/repos`.
4. Without `--repo`, only remote-scope providers run.
5. With a resolved repo, results can include Exa Code Context, grep.app, DeepWiki, local exact search, and Morph when configured.
6. `--format` accepts `markdown` or `json`.
7. JSON output is section-aware: matches stay separate from DeepWiki answers, and provider failures are reported in `errors[]`.
8. `No results found.` is a valid result, not a shell failure.
9. Exit code `0` does not guarantee every backend succeeded. Provider sections or JSON `errors[]` can still reflect backend failures.

Examples:

```bash
uv run csearch code "search_web" --repo mnm-matin/captain-search
uv run csearch code "FastMCP" --repo https://github.com/mnm-matin/captain-search --format json
```

## fetch

1. Use `fetch` for HTML pages, GitHub blob URLs, PDFs, and other documents.
2. Use `--format markdown` by default.
3. Use `--format json` when you need URL, title, status, and content length alongside the content.
4. GitHub blob URLs are normalized to raw content automatically.
5. Remote extraction is auto-selected across configured providers with weighted fallback. If remote providers fail or return junk, local extraction is used.
6. JSON fetch output wraps the cleaned markdown content; it does not return raw provider payloads.

Examples:

```bash
uv run csearch fetch https://example.com --format json
uv run csearch fetch https://github.com/mnm-matin/captain-search/blob/main/README.md
```

## mcp

1. Use `mcp` to run the MCP server.
2. `mcp` accepts `--transport`, `--host`, and `--port`.
3. Bare `csearch` no longer starts the server.

Examples:

```bash
uv run csearch mcp
uv run csearch mcp --transport http --port 8000 --host 0.0.0.0
```

## version

1. Use `version` to print the CLI version without needing a global flag.

Example:

```bash
uv run csearch version
```

## doctor

1. Use `doctor` when providers appear disabled, empty, cooling down, or rate-limited.
2. The report summarizes enabled providers, detected keys, cooldown state, and recent telemetry.

Example:

```bash
uv run csearch doctor
```

## skill install

1. Use `skill install` to install or refresh the Captain Search CLI skill.
2. `--scope user` installs under the home directory. `--scope project` installs under the current working directory.
3. `--target auto` prefers `.agents/skills`. Use `--target claude` when the user explicitly wants Claude Code skill paths.
4. `--runtime auto` uses the source checkout when available and falls back to the published `uvx` form otherwise.
5. Use `--force` to overwrite an existing Captain Search skill install.

Examples:

```bash
uv run csearch skill install --scope user
uv run csearch skill install --scope project --target claude --force
```

## Exit codes

1. Exit code `0` means the command returned a top-level success, including valid empty outputs and partial backend failures.
2. Exit code `1` means the command returned a top-level error.
3. Exit code `2` means argparse usage or validation failure, such as an invalid subcommand or out-of-range `--max-results`.

## Common mistakes

1. Do not confuse short CLI subcommands with underscore MCP tool names.
2. Do not use legacy `search-web`, `search-code`, `fetch-webpage`, or `serve` commands.
3. Do not use published-package `uvx` examples until a published package exists.
4. Do not forget that bare `captain-search` or `csearch` only prints help. Use `mcp` explicitly for server mode.