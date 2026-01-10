<div align="center">
  <h1>🧭 Captain Search</h1>
  <p><strong>One MCP server for all your web search needs</strong></p>
  <p>Aggregate multiple search providers with automatic load balancing and fallback</p>
</div>

<p align="center">
  <a href="https://github.com/mnm-matin/captain-search/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://pypi.org/project/captain-search/"><img src="https://img.shields.io/pypi/v/captain-search.svg" alt="PyPI"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"></a>
</p>

---

## Why Captain Search?

- 🔄 **Auto-rotation** between providers based on free tier limits
- ⚡ **Automatic fallback** when a provider fails  
- 🔗 **Parallel search** across all providers for comprehensive results
- 📄 **Built-in webpage extraction** via Jina Reader

---

## Supported Providers

You only need **one** provider to get started. Add more for redundancy.

| Provider | Free Tier | Best For | Get API Key |
|----------|-----------|----------|-------------|
| **Serper** | 2,500/month | Google results | [serper.dev](https://serper.dev) |
| **Brave** | 2,000/month | Independent index | [brave.com/search/api](https://brave.com/search/api/) |
| **Tavily** | 1,000/month | AI-optimized results | [app.tavily.com](https://app.tavily.com) |
| **Exa** | $10 credit | Neural/semantic search | [dashboard.exa.ai](https://dashboard.exa.ai/api-keys) |
| **Perplexity** | $5/mo credit | AI-powered answers | [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api) |
| **Jina** | 1M tokens | Webpage/PDF extraction | [jina.ai/reader](https://jina.ai/reader/) |

> 💡 **Tip:** Serper + Brave = 4,500 free searches/month with automatic failover

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
      "command": "uvx",
      "args": ["captain-search"],
      "env": {
        "SERPER_API_KEY": "your-key-here"
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
      "command": "uvx",
      "args": ["captain-search"],
      "env": {
        "SERPER_API_KEY": "your-key-here",
        "BRAVE_API_KEY": "your-key-here"
      }
    }
  }
}
```

</details>

<details>
<summary><b>Install in Claude Code</b></summary>

```bash
claude mcp add captain-search -e SERPER_API_KEY=your-key -- uvx captain-search
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
        "command": "uvx",
        "args": ["captain-search"],
        "env": {
          "SERPER_API_KEY": "your-key-here"
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
      "command": "uvx",
      "args": ["captain-search"],
      "env": {
        "SERPER_API_KEY": "your-key-here"
      }
    }
  }
}
```

</details>

<details>
<summary><b>Using pip instead of uvx</b></summary>

If you prefer pip:

```bash
pip install captain-search
```

Then replace `"command": "uvx", "args": ["captain-search"]` with:

```json
"command": "captain-search"
```

</details>

---

## Available Tools

| Tool | Description |
|------|-------------|
| `search_web` | Search with auto-rotating providers and fallback |
| `search_multi` | Search ALL providers in parallel, deduplicate results |
| `fetch_webpage` | Extract content from any URL (articles, PDFs, docs) |

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
3. **Multi-Provider**: `search_multi` queries all in parallel

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
