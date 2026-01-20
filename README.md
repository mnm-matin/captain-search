<h1 align="center">Captain Search</h1>

<p align="center">
  <strong>Unified web and code search for MCP agents</strong><br>
  One server. Multiple providers. Clean Markdown.
</p>

<p align="center">
  <img src="docs/banner.svg" alt="Captain Search – Web and code search for MCP agents" width="600" />
</p>

<p align="center">
  <a href="https://github.com/mnm-matin/captain-search/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python"></a>
</p>

---

## Supported Providers

### Web Search

You only need **one** provider to get started. Add more for redundancy.

| Provider | Free Tier | Best For | Get API Key |
|----------|-----------|----------|-------------|
| **Serper** | 2,500/month | Google results | [serper.dev](https://serper.dev) |
| **Brave** | 2,000/month | Independent index | [brave.com/search/api](https://brave.com/search/api/) |
| **Tavily** | 1,000/month | AI-optimized results | [app.tavily.com](https://app.tavily.com) |
| **Exa** | $10 credit | Neural/semantic search | [dashboard.exa.ai](https://dashboard.exa.ai/api-keys) |
| **Perplexity** | $5/mo credit | AI-powered answers | [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api) |

> 💡 **Tip:** Serper + Brave = 4,500 free searches/month with automatic failover

### Code Search

| Provider | Free Tier | Best For | Get API Key |
|----------|-----------|----------|-------------|
| **Exa (MCP)** | Unlimited* | Semantic code context | [exa.ai](https://exa.ai) |
| **grep.app** | Free (no key) | Exact text matching | [grep.app](https://grep.app) |
| **DeepWiki** | Free (MCP) | Repo Q&A / Architecture | [deepwiki.com](https://deepwiki.com) |
| **Noodlbox** | Free (local) | Local graph analysis | [noodlbox.io](https://noodlbox.io) |

### Webpage Extraction

| Provider | Free Tier | Best For | Get API Key |
|----------|-----------|----------|-------------|
| **Jina** | 1M tokens | Webpage/PDF extraction | [jina.ai/reader](https://jina.ai/reader/) |

---

## Installation

<details>
<summary><b>Install in Cursor</b></summary>

Go to: `Settings` → `Cursor Settings` → `MCP` → `Add new global MCP server`

Add to your `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "captain-search": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/captain-search", "captain-search"],
      "env": {
        "SERPER_API_KEY": "your-key-here",
        "BRAVE_API_KEY": "",
        "TAVILY_API_KEY": "",
        "EXA_API_KEY": "",
        "PERPLEXITY_API_KEY": "",
        "JINA_API_KEY": ""
      }
    }
  }
}
```

</details>

<details>
<summary><b>Install in Claude Desktop</b></summary>

Add to your Claude Desktop config:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "captain-search": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/captain-search", "captain-search"],
      "env": {
        "SERPER_API_KEY": "your-key-here",
        "BRAVE_API_KEY": "",
        "TAVILY_API_KEY": "",
        "EXA_API_KEY": "",
        "PERPLEXITY_API_KEY": "",
        "JINA_API_KEY": ""
      }
    }
  }
}
```

</details>

<details>
<summary><b>Install in Claude Code</b></summary>

```bash
claude mcp add captain-search -e SERPER_API_KEY=your-key -- uv run --directory /path/to/captain-search captain-search
```

</details>

<details>
<summary><b>Install in VS Code</b></summary>

Add to your User Settings (JSON) via `Ctrl+Shift+P` → `Preferences: Open User Settings (JSON)`:

```json
{
  "mcp": {
    "servers": {
      "captain-search": {
        "command": "uv",
        "args": ["run", "--directory", "/path/to/captain-search", "captain-search"],
        "env": {
          "SERPER_API_KEY": "your-key-here",
          "BRAVE_API_KEY": "",
          "TAVILY_API_KEY": "",
          "EXA_API_KEY": "",
          "PERPLEXITY_API_KEY": "",
          "JINA_API_KEY": ""
        }
      }
    }
  }
}
```

Or add to `.vscode/mcp.json` in your workspace to share with your team.

</details>

<details>
<summary><b>Install in Windsurf</b></summary>

Add to your `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "captain-search": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/captain-search", "captain-search"],
      "env": {
        "SERPER_API_KEY": "your-key-here",
        "BRAVE_API_KEY": "",
        "TAVILY_API_KEY": "",
        "EXA_API_KEY": "",
        "PERPLEXITY_API_KEY": "",
        "JINA_API_KEY": ""
      }
    }
  }
}
```

</details>

<details>
<summary><b>Getting Started</b></summary>

```bash
git clone https://github.com/mnm-matin/captain-search.git
cd captain-search
uv sync
```

Then update `/path/to/captain-search` in the configs above to your actual path.

</details>

---

## Available Tools

| Tool | Description |
|------|-------------|
| `search_web` | Search with weighted selection and optional multi-provider mode |
| `search_code` | Search code across Exa, grep.app, DeepWiki, and Noodl |
| `fetch_webpage` | Extract content from any URL (articles, PDFs, docs) |

`search_web` provider selector:
- `auto` (default): weighted single-provider selection with fallback
- `multi` or `all`: parallel search across all enabled providers
- Provider name: `serper`, `brave`, `tavily`, `perplexity`, `exa`, `exa_mcp`
- Comma-separated list for multi-provider search

`search_code` providers:
- **Exa Code Context**: Semantic search (always runs)
- **grep.app**: Exact text matching (always runs)
- **DeepWiki**: Repo Q&A (requires repo filter)
- **Noodl**: Local graph analysis (requires repo filter + cloned repo)

---

## Running as a Remote Server

For teams or cloud deployment:

```bash
# HTTP mode
captain-search --transport http --port 8000

# SSE mode  
captain-search --transport sse --port 8000
```

### With Authentication

```bash
export MCP_AUTH_TOKEN="your-secret-token"
captain-search --transport http --port 8000
```

Connect via:
- Header: `Authorization: Bearer your-secret-token`
- Query: `http://host:8000/mcp?token=your-secret-token`

### Claude Desktop (Remote)

```json
{
  "mcpServers": {
    "captain-search": {
      "url": "http://your-server:8000/mcp?token=your-secret-token"
    }
  }
}
```

---

## Environment Variables

| Variable | Required |
|----------|----------|
| `SERPER_API_KEY` | At least one provider |
| `BRAVE_API_KEY` | At least one provider |
| `TAVILY_API_KEY` | At least one provider |
| `EXA_API_KEY` | Optional |
| `PERPLEXITY_API_KEY` | Optional |
| `JINA_API_KEY` | Optional (works without) |
| `MCP_AUTH_TOKEN` | For remote mode |

---

## How It Works

1. **Weighted Selection**: Providers chosen based on free tier limits
2. **Automatic Fallback**: If one fails, tries the next
3. **Multi-Provider**: `search_web` in `multi` mode queries all in parallel

Default weights: Serper (42%) → Brave (33%) → Tavily (17%) → Perplexity (8%)

Customize via `config.yaml`:

```yaml
providers:
  serper:
    weight: 50
    enabled: true
  brave:
    weight: 30
    enabled: true
```

---

## Docker

```bash
docker build -t captain-search .

docker run -p 8000:8000 \
  -e SERPER_API_KEY=your_key \
  -e MCP_AUTH_TOKEN=your_secret \
  captain-search --transport http --port 8000
```

---

## Development

```bash
git clone https://github.com/mnm-matin/captain-search.git
cd captain-search
uv pip install -e ".[dev]"
pytest
```

---

## License

MIT License - see [LICENSE](LICENSE)

---

<p align="center">
  <sub>Built with ❤️ for the AI agent ecosystem</sub>
</p>
