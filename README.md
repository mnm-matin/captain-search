<p align="center">
  <h1 align="center">🧭 Captain Search</h1>
  <p align="center">
    <strong>One MCP server for all your search needs</strong>
  </p>
  <p align="center">
    A unified search API that aggregates multiple providers with automatic load balancing, fallback, and MCP support.
  </p>
</p>

<p align="center">
  <a href="https://github.com/mnm-matin/captain-search/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://pypi.org/project/captain-search/"><img src="https://img.shields.io/pypi/v/captain-search.svg" alt="PyPI"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"></a>
</p>

---

## Why Captain Search?

Most AI agents need web search. But each search API has different rate limits, pricing, and quirks. **Captain Search** solves this by:

- 🔄 **Auto-rotating** between providers based on their free tier limits
- ⚡ **Automatic fallback** if one provider fails
- 🔗 **Parallel search** across all providers for comprehensive results  
- 📄 **Built-in web scraping** via Jina Reader
- 🔐 **Optional auth** for remote deployment

---

## Quickstart (30 seconds)

### 1. Install

```bash
pip install captain-search
```

### 2. Set ONE API key

```bash
export SERPER_API_KEY=your_key_here
```

### 3. Run

```bash
captain-search
```

That's it! You now have a working MCP server. Add more providers for redundancy.

---

## Supported Providers

You only need **ONE** provider to get started. Add more for redundancy and higher limits.

| Provider | Free Tier | Rate Limit | Best For | Get API Key |
|----------|-----------|------------|----------|-------------|
| **Serper** | 2,500/month | 50 req/sec | Google results, fast | [serper.dev](https://serper.dev) |
| **Brave** | 2,000/month | 1 req/sec | Privacy-focused, independent index | [brave.com/search/api](https://brave.com/search/api/) |
| **Tavily** | 1,000/month | — | AI-optimized, clean results | [tavily.com](https://app.tavily.com) |
| **Exa** | $10 credit | — | Semantic/neural search | [dashboard.exa.ai](https://dashboard.exa.ai/api-keys) |
| **Perplexity** | $5/mo credit | — | AI-powered answers | [perplexity.ai](https://www.perplexity.ai/settings/api) |
| **Jina** | 1M tokens | 20 req/min | Web scraping, PDF extraction | [jina.ai](https://jina.ai/reader/) |

> 💡 **Tip:** Serper + Brave gives you 4,500 free searches/month with automatic failover.

---

## MCP Tools

Captain Search exposes 3 tools to your AI assistant:

| Tool | Description |
|------|-------------|
| `search_web` | Search with auto-rotating providers and fallback |
| `search_multi` | Search ALL providers in parallel, deduplicate results |
| `fetch_webpage` | Extract content from any URL (articles, PDFs, docs) |

---

## Configuration

### Claude Desktop / Claude Code

Add to your config file:

<details>
<summary><strong>📍 Config file locations</strong></summary>

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

</details>

```json
{
  "mcpServers": {
    "captain-search": {
      "command": "captain-search",
      "env": {
        "SERPER_API_KEY": "your_serper_key",
        "BRAVE_API_KEY": "your_brave_key"
      }
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project or global config:

```json
{
  "mcpServers": {
    "captain-search": {
      "command": "captain-search",
      "env": {
        "SERPER_API_KEY": "your_serper_key"
      }
    }
  }
}
```

### VS Code (Copilot)

Add to your User Settings (JSON) or `.vscode/mcp.json`:

```json
{
  "mcp": {
    "servers": {
      "captain-search": {
        "command": "captain-search",
        "env": {
          "SERPER_API_KEY": "your_serper_key"
        }
      }
    }
  }
}
```

---

## 🤖 Agent Setup Instructions

Copy and paste this to your AI assistant to help it set up Captain Search:

<details>
<summary><strong>📋 Click to copy setup instructions for your agent</strong></summary>

```
I want you to help me set up Captain Search, an MCP server for web search.

Here's what I need:
1. Install it: pip install captain-search (or uv pip install captain-search)
2. I need to set at least ONE of these API keys as environment variables:
   - SERPER_API_KEY (get free at serper.dev - 2,500/month)
   - BRAVE_API_KEY (get free at brave.com/search/api - 2,000/month)  
   - TAVILY_API_KEY (get free at tavily.com - 1,000/month)
3. Add to my MCP config (Claude Desktop, Cursor, or VS Code):

{
  "mcpServers": {
    "captain-search": {
      "command": "captain-search",
      "env": {
        "SERPER_API_KEY": "my_key_here"
      }
    }
  }
}

Once configured, you'll have access to:
- search_web: Search the web with automatic provider rotation
- search_multi: Search all providers in parallel  
- fetch_webpage: Extract content from URLs

Help me get this set up!
```

</details>

---

## Remote Server Mode

Run Captain Search as a remote HTTP/SSE server for teams or cloud deployment:

```bash
# HTTP mode
captain-search --transport http --port 8000

# SSE mode  
captain-search --transport sse --port 8000
```

### Securing with Auth Token

```bash
export MCP_AUTH_TOKEN="your-secret-token"
captain-search --transport http --port 8000
```

Clients connect via:
- Header: `Authorization: Bearer your-secret-token`
- Query param: `http://host:8000/mcp?token=your-secret-token`

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

| Variable | Description | Required |
|----------|-------------|----------|
| `SERPER_API_KEY` | Serper.dev API key | At least one |
| `BRAVE_API_KEY` | Brave Search API key | At least one |
| `TAVILY_API_KEY` | Tavily API key | At least one |
| `EXA_API_KEY` | Exa AI API key | Optional |
| `PERPLEXITY_API_KEY` | Perplexity API key | Optional |
| `JINA_API_KEY` | Jina Reader API key | Optional (works without) |
| `MCP_AUTH_TOKEN` | Bearer token for remote mode | Optional |

---

## How Provider Selection Works

1. **Weighted Random**: Providers are selected based on weights (default: proportional to free tier limits)
2. **Automatic Fallback**: If selected provider fails, others are tried in order
3. **Multi-Provider**: `search_multi` queries all enabled providers in parallel

Default weights:
- Serper: 42% (2,500/month)
- Brave: 33% (2,000/month)
- Tavily: 17% (1,000/month)
- Perplexity: 8%

Customize via `config.yaml`:

```yaml
providers:
  serper:
    weight: 50
    enabled: true
  brave:
    weight: 30
    enabled: true
  tavily:
    weight: 20
    enabled: true
```

---

## Docker

```bash
docker build -t captain-search .

docker run -d -p 8000:8000 \
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

# Run tests
pytest

# Lint
ruff check src/
```

---

## License

MIT License - see [LICENSE](LICENSE)

---

## Contributing

Contributions welcome! Feel free to open issues or submit PRs.

---

<p align="center">
  <sub>Built with ❤️ for the AI agent ecosystem</sub>
</p>
