# Setup

## Installation

```bash
# From PyPI (when published)
uv tool install captain-search

# Or run directly without installing
uvx --from captain-search csearch web "test query"
```

After installation, `csearch` and `captain-search` are both available — they are identical.

## Provider API keys

Captain Search works out of the box with zero API keys — the default `exa_mcp` provider requires no key. For better coverage and redundancy, add provider keys.

Set keys as environment variables or in a `.env` file in your working directory.

### Web search providers

| Provider | Env var | Notes |
|----------|---------|-------|
| Serper | `SERPER_API_KEY` | Google search results |
| Brave | `BRAVE_API_KEY` | Brave search results |
| Tavily | `TAVILY_API_KEY` | Also used for fetch |
| Perplexity | `PERPLEXITY_API_KEY` | AI-powered search |
| Parallel | `PARALLEL_API_KEY` | Also used for fetch |
| Exa | `EXA_API_KEY` | API access; `exa_mcp` works without a key |

### Fetch providers

| Provider | Env var | Notes |
|----------|---------|-------|
| Jina | `JINA_API_KEY` | Optional — works without key |
| Tavily | `TAVILY_API_KEY` | Shared with web |
| Parallel | `PARALLEL_API_KEY` | Shared with web |
| Exa | `EXA_API_KEY` | Shared with web |

### Code search providers

| Provider | Auth | Notes |
|----------|------|-------|
| Exa MCP | None or `EXA_API_KEY` | Enabled by default |
| grep.app | None | Public, best-effort |
| DeepWiki | None | Only for public indexed repos |
| GitHub Code Search | `gh` CLI authenticated | Runs `gh auth token`; skipped if `gh` is not installed |
| Morph | `MORPH_API_KEY` + `MORPH_BASE_URL` | Repo-local only |

### Key rotation

All providers support multiple keys via `<PROVIDER>_API_KEYS` (comma-separated). Keys are rotated automatically and cooled down individually on errors.

```bash
SERPER_API_KEYS=key1,key2,key3
```

## Config file (optional)

Place a `config.yaml` in your working directory to adjust provider weights or disable providers:

```yaml
providers:
  serper:
    weight: 40
    enabled: true
  brave:
    weight: 30
    enabled: true
  exa_mcp:
    weight: 20
    enabled: true
  perplexity:
    weight: 10
    enabled: false
```

Config lookup order: `config.yaml` → `config.yml` → `captain_search.yaml`. Environment variables override config file values.

## Health and cooldowns

Captain Search tracks provider health automatically:

- **Rate-limited keys** (429) are cooled with exponential backoff (30s → 900s max).
- **Auth failures** (401/403) cool the specific key for 1 hour.
- **Provider failures** use exponential backoff (15s → 120s).

Health state persists at `~/.captain-search/health.json`.

Run `csearch doctor` to inspect current health, cooldowns, and recent telemetry.

## Logging

| Env var | Default | Purpose |
|---------|---------|---------|
| `CAPTAIN_SEARCH_LOG_ENABLED` | true | Enable/disable telemetry logging |
| `CAPTAIN_SEARCH_LOG_DIR` | `~/.captain-search/logs` | Log directory |

Logs are daily JSONL files at `~/.captain-search/logs/YYYY-MM-DD.jsonl`.
