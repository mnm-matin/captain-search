# CLI Design

This document describes the current Captain Search CLI as implemented today, plus a short list of next changes worth considering.

---

## Current CLI (as implemented)

### Principles

1. Short commands. The binary name already implies search.
2. No implicit server mode. MCP server requires an explicit subcommand.
3. Positional arguments are used for the main query or URL input.
4. Breadth control (`--all`) is separate from provider selection (`--provider`).
5. Markdown is the default output. JSON is opt-in.
6. One flag name maps to one concept across subcommands.

### Entry Points

Two installed commands, both pointing to `captain_search.server:main`:

```
captain-search   # long form
csearch          # short form used in docs
```

### No-Subcommand Behavior

Running `csearch` with no arguments prints help and exits `0`.

```bash
csearch
csearch --help
```

There is no implicit server mode.

### Subcommands

```
csearch web <query>                    Search the web
csearch code <query> [--repo <repo>]   Search code
csearch fetch <url>                    Fetch and extract a webpage or document
csearch doctor                         Diagnose providers, telemetry, and cooldown state
csearch skill install                  Install or refresh the Captain Search CLI skill
csearch mcp                            Run the MCP server
csearch version                        Print version and exit
```

### Flags

**Global:**
- `--version` — print version and exit
- `-h` / `--help`

**web:**

```bash
csearch web <query>
csearch web <query> --all
csearch web <query> --provider brave
csearch web <query> --provider brave,serper
csearch web <query> --max-results 5
csearch web <query> --format json
```

| Flag | Values | Default |
|------|--------|---------|
| `--all` | boolean | false |
| `--provider` | provider name or comma-separated list | auto weighted selection |
| `--max-results` | 1–50 | 10 |
| `--format` | markdown, json | markdown |

`--all` and `--provider` are mutually exclusive.

**code:**

```bash
csearch code <query>
csearch code <query> --repo mnm-matin/captain-search
csearch code <query> --repo .
csearch code <query> --format json
```

| Flag | Values | Default |
|------|--------|---------|
| `--repo` | owner/repo, Git URL, local path, `file://` path | none |
| `--format` | markdown, json | markdown |

**fetch:**

```bash
csearch fetch <url>
csearch fetch <url> --format json
```

| Flag | Values | Default |
|------|--------|---------|
| `--format` | markdown, json | markdown |

JSON wraps the cleaned markdown content with metadata.

**mcp:**

```bash
csearch mcp
csearch mcp --transport http --port 8000
```

| Flag | Values | Default |
|------|--------|---------|
| `--transport` | stdio, http, sse | stdio |
| `--port` | integer | 8000 |
| `--host` | address | 0.0.0.0 |

**doctor:** no flags.

**skill install:**

```bash
csearch skill install
csearch skill install --scope project
csearch skill install --target claude
csearch skill install --runtime uvx --force
```

| Flag | Values | Default |
|------|--------|---------|
| `--scope` | user, project | user |
| `--target` | auto, agents, claude | auto |
| `--runtime` | auto, repo, uvx, installed | auto |
| `--force` | boolean | false |

**version:** no flags.

### Structured Output for Code Search

`csearch code --format json` returns a typed, section-aware schema:

```json
{
  "query": "search_web",
  "repo": {
    "input": "mnm-matin/captain-search",
    "full_name": "mnm-matin/captain-search",
    "local_path": "/Users/.../captain-search"
  },
  "sections": [
    {
      "type": "matches",
      "source": "exa_mcp",
      "title": "Exa Code Context",
      "items": [
        {
          "title": "src/captain_search/server.py",
          "url": "https://github.com/...",
          "content": "..."
        }
      ]
    },
    {
      "type": "answer",
      "source": "deepwiki",
      "title": "DeepWiki",
      "content": "Captain Search exposes web, code, and fetch tools through one MCP server."
    }
  ],
  "warnings": [],
  "errors": [
    {
      "source": "grep_app",
      "message": "Rate limit exceeded on grep.app. Try again later or pass --repo to enable repo-scoped providers."
    }
  ]
}
```

This preserves the semantic difference between code matches, repo explanations, and provider failures.

### Structured Output for Fetch

`csearch fetch --format json` wraps content with metadata:

```json
{
  "url": "https://example.com/docs",
  "title": "Example Documentation",
  "status": 200,
  "content_length": 4523,
  "content": "# Example\n\nThis is the extracted content..."
}
```

### Exit Codes

- `0` — command succeeded (partial provider failures remain `0`)
- `1` — top-level command failure
- `2` — invalid CLI usage (argparse)

### Example Sessions

```bash
# Quick web lookup
csearch web "openai api"

# Broad search across all providers
csearch web "react server actions caching" --all

# Structured web results
csearch web "python asyncio" --format json --max-results 5

# Code search in a specific repo
csearch code "search_web" --repo mnm-matin/captain-search

# Structured code results
csearch code "search_web" --repo mnm-matin/captain-search --format json

# Fetch a page
csearch fetch https://example.com/docs

# Fetch with metadata
csearch fetch https://example.com/docs --format json

# Diagnose providers
csearch doctor

# Install the reusable CLI skill
csearch skill install --scope user

# Start MCP server
csearch mcp --transport stdio

# Print version
csearch version
```


---

## Next Changes I Would Propose

1. Add `doctor --format json` so environment checks are scriptable.
2. Add shell completion generation for `bash`, `zsh`, and `fish`.
3. Expose the selected fetch provider in `fetch --format json` output for easier debugging.
