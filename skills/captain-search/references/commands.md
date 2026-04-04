# Command Reference

Detailed examples and output patterns for each command.

## web

### Basic searches

```bash
# Simple query
csearch web "openai function calling"

# Limit results
csearch web "python asyncio tutorial" --max-results 5

# Site-scoped query
csearch web "rate limiting site:docs.stripe.com"
```

### Provider control

```bash
# All providers in parallel (best coverage)
csearch web "react server components" --all

# Specific provider
csearch web "kubernetes pod scheduling" --provider brave

# Multiple specific providers
csearch web "docker compose networking" --provider serper,brave
```

### Output format

Default output is numbered sections:

```
## 1. Title of Result

**URL:** https://example.com/article

Content snippet describing the result...

## 2. Another Result

**URL:** https://example.com/other
...
```

Warnings appear at the top when a provider partially fails:

```
**Warning:** Provider xyz returned an error but other providers succeeded.

## 1. Title
...
```

### Provider selection behavior

- **Auto** (default): picks one provider by weight, falls back to the next healthy provider on failure.
- **All** (`--all`): runs every enabled provider in parallel, merges and deduplicates results.
- **Explicit** (`--provider name`): runs only the named provider(s).

## code

### Remote code search

```bash
# Search across public code indexes
csearch code "useEffect cleanup"

# Search a specific GitHub repo
csearch code "handleRequest" --repo expressjs/express

# Search by Git URL
csearch code "middleware" --repo https://github.com/pallets/flask
```

### Local code search

```bash
# Search the current repo
csearch code "database connection" --repo .

# Search a local path
csearch code "config parser" --repo /path/to/project

# file:// prefix also works
csearch code "test helper" --repo file:///path/to/project
```

### Output format

Results are grouped by provider source:

```
## Exa Code Context

### 1. src/server.py — Server Setup
https://github.com/user/repo/blob/main/src/server.py

    def setup_server():
        app = FastAPI()
        ...

## DeepWiki

Captain Search uses FastAPI for its HTTP transport layer...

## Local Exact Search

### 1. src/config.py (lines 15-22)

    def load_config():
        ...
```

When no provider returns results, the output says `No results found.`

### What runs when

| Scenario | Providers used |
|----------|---------------|
| No `--repo` | Exa MCP, grep.app |
| `--repo owner/repo` | Exa MCP, grep.app, GitHub Code Search, DeepWiki, local exact search |
| `--repo .` (local only, no remote) | Local exact search, Morph (if configured) |
| `--repo .` (local with remote origin) | All of the above |

## fetch

### Common uses

```bash
# Extract a webpage
csearch fetch https://docs.python.org/3/library/asyncio.html

# Read a GitHub file (blob URL auto-normalized to raw)
csearch fetch https://github.com/user/repo/blob/main/README.md

# Fetch a PDF
csearch fetch https://example.com/paper.pdf
```

### Output format

Clean extracted content in markdown:

```
# Page Title

Main content of the page, with navigation and boilerplate stripped...
```

Content is truncated at ~40,000 characters.

### How extraction works

1. Tries a remote provider (Jina, Exa, Tavily, or Parallel) selected by weight.
2. Falls back to other remote providers on failure.
3. If all remote providers fail: extracts locally using trafilatura (HTML), pypdf (PDF), or raw text decoding.
4. GitHub blob URLs are automatically converted to raw URLs before fetching.

## doctor

```bash
csearch doctor
```

Example output:

```
# Captain Search Doctor

## Provider Status

| Provider | Enabled | Keys | Status | Recent (24h) |
|----------|---------|------|--------|--------------|
| serper | yes | 2 | healthy | 15 ok, 0 err |
| brave | yes | 1 | cooling (2m) | 8 ok, 2 err |
| exa_mcp | yes | 0 | healthy | 5 ok, 0 err |
| github_code_search | yes | gh | healthy | 3 ok, 0 err |

## Key Cooldowns

| Provider | Key | Status | Reason | Remaining |
|----------|-----|--------|--------|-----------|
| brave | sk-...3f | cooling | 429 rate limit | 1m 45s |
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Command completed (partial provider failures still exit 0) |
| 1 | Top-level failure (all providers failed, or fatal error) |
| 2 | Invalid CLI usage |
