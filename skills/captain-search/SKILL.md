---
name: captain-search
description: 'Search the web, search code, and fetch webpages using the csearch CLI. Use when the user needs web search results, code search across repos, webpage content extraction, or provider troubleshooting. Triggers: "search the web", "find code", "fetch this page", "look up", "search for", "what does this page say", "extract content from", "csearch", "captain search".'
argument-hint: 'Describe what to search, fetch, or diagnose'
---

# Captain Search CLI

Three commands: `web` for web search, `code` for code search, `fetch` for page extraction.

## When to use which command

| Need | Command |
|------|---------|
| Web search results (links, snippets) | `csearch web "query"` |
| Find code in a repo or across public repos | `csearch code "query"` |
| Extract content from a URL (HTML, PDF, GitHub blob) | `csearch fetch <url>` |
| Check provider health and API key status | `csearch doctor` |

## Commands

### web — search the web

```bash
csearch web "your search query"
csearch web "your query" --max-results 5
csearch web "your query" --all
csearch web "your query" --provider brave
csearch web "your query" --provider brave,serper
```

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--max-results` | 1–50 | 10 | Results after dedup |
| `--all` | flag | off | Query all providers in parallel |
| `--provider` | name or comma list | auto | Mutually exclusive with `--all` |

**Provider selection:**
- Default (no flag): picks the best available provider by weight with automatic fallback.
- `--all`: fans out to every enabled provider, merges and deduplicates results.
- `--provider <name>`: targets a specific provider. Comma-separated names run those providers in parallel.

Valid provider names: `serper`, `brave`, `tavily`, `perplexity`, `parallel`, `exa`, `exa_mcp`.

### code — search code

```bash
csearch code "function_name"
csearch code "search_web" --repo owner/repo
csearch code "handler" --repo .
csearch code "setup" --repo https://github.com/user/repo
```

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--repo` | owner/repo, Git URL, local path, `file://` path | none | Scope to a specific repo |

**Repo scoping:**
- No `--repo`: searches across public code indexes only.
- `--repo owner/repo` or Git URL: searches remote indexes plus clones the repo for local matching.
- `--repo .` or local path: searches the local repo. If it has a remote origin, remote providers also run.
- Remote repos are cached under `~/.cache/captain-search/repos`.

Eligible providers are selected automatically based on context: Exa, grep.app, DeepWiki, local exact search, GitHub Code Search (requires `gh` CLI auth), and Morph (requires `MORPH_API_KEY`).

### fetch — extract webpage content

```bash
csearch fetch https://example.com/docs
csearch fetch https://github.com/user/repo/blob/main/README.md
```

No additional flags needed for typical use. Handles HTML pages, GitHub blob URLs (auto-normalized to raw), and PDFs.

Provider selection is automatic with weighted fallback. If all remote providers fail, falls back to local extraction.

### doctor — diagnose provider health

```bash
csearch doctor
```

Shows: enabled providers, configured API keys, cooldown status, and recent success/error/rate-limit counts. Run this when results are empty or a provider seems broken.

### version

```bash
csearch version
```

## Rules

1. Use the short subcommands: `web`, `code`, `fetch`, `doctor`, `version`.
2. Never use legacy names (`search-web`, `search-code`, `fetch-webpage`).
3. Bare `csearch` prints help and exits 0.
4. Use `--all` for breadth, not `--provider multi` or `--provider all`.
5. Exit code 0 means the command completed — partial provider failures can still appear as warnings in the output.
6. `No results found.` is a valid outcome, not a failure.

## Setup

For provider configuration, API keys, and installation, read [references/setup.md](./references/setup.md).
For detailed command examples and output interpretation, read [references/commands.md](./references/commands.md).

## Troubleshooting

1. Run `csearch doctor` first.
2. Check if the failing provider has a valid API key configured.
3. If a provider is cooling down, wait or switch to `--all` to use other providers.
4. Inspect `~/.captain-search/logs/` for detailed request logs.
