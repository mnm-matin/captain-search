# Captain Search

A unified search API that aggregates multiple search providers (Serper, Brave, Tavily, Perplexity) with automatic load balancing, fallback, and MCP (Model Context Protocol) support.

## Features

- 🔍 **Unified search** across multiple providers with a single API
- ⚡ **Weighted random selection** based on free tier limits
- 🔄 **Automatic fallback** if a provider fails
- 🔗 **Multi-provider search** - query all providers in parallel
- 📄 **Webpage/PDF extraction** via Jina Reader
- 🤖 **MCP server** for Claude Desktop and other AI assistants
- 🐳 **Docker support** for easy deployment

## Quick Start

### Installation

```bash
# Using pip
pip install captain-search

# Using uv (recommended)
uv pip install captain-search
```

### From Source

```bash
git clone https://github.com/yourusername/captain-search.git
cd captain-search
uv pip install -e .
```

### Set API Keys

```bash
# At minimum, set one provider key:
export SERPER_API_KEY=your_key_here

# Or set multiple for redundancy:
export SERPER_API_KEY=your_serper_key
export BRAVE_API_KEY=your_brave_key
export TAVILY_API_KEY=your_tavily_key
export PERPLEXITY_API_KEY=your_perplexity_key
```

### Run the Server

```bash
# Stdio mode (for Claude Desktop)
captain-search

# HTTP mode
captain-search --transport http --port 8000

# SSE mode
captain-search --transport sse --port 8000
```

### Optional: Secure the Remote MCP Endpoint

If you are running Captain Search as a **remote** MCP server (HTTP/SSE) on a
publicly reachable host, you can protect it with a simple static bearer token.

```bash
export MCP_AUTH_TOKEN="your-secret-token"
captain-search --transport http --port 8000
```

Clients must send:

```
Authorization: Bearer your-secret-token
```

If your MCP client cannot set custom HTTP headers, Captain Search also accepts the
token as a URL query parameter (less secure; may be logged):

- `http://localhost:8000/mcp?api_key=your-secret-token`
- `http://localhost:8000/mcp?token=your-secret-token`

## Getting API Keys

You only need **ONE** provider to get started. Add more for redundancy.

| Provider | Free Tier | How to Get |
|----------|-----------|------------|
| **Serper** | 2,500/month | Sign up at [serper.dev](https://serper.dev) |
| **Brave** | 2,000/month | Sign up at [brave.com/search/api](https://brave.com/search/api/) |
| **Tavily** | 1,000/month | Sign up at [tavily.com](https://tavily.com) |
| **Perplexity** | ~$5/month credit | Requires [Perplexity Pro](https://perplexity.ai) subscription |
| **Jina** | 20 req/min | Optional - works without key (rate limited) at [jina.ai](https://jina.ai/reader/) |

## MCP Tools

The server exposes three MCP tools:

### `search_web`

Search the web using weighted random provider selection with automatic fallback.

```json
{
  "query": "latest AI developments",
  "max_results": 10,
  "format": "markdown"
}
```

### `search_multi`

Search all providers in parallel and combine results.

```json
{
  "query": "climate change solutions",
  "max_results_per_provider": 5,
  "providers": ["serper", "brave"],
  "deduplicate": true,
  "format": "markdown"
}
```

### `search_fetch_webpage`

Fetch and extract content from a webpage or PDF.

```json
{
  "url": "https://example.com/article",
  "format": "markdown"
}
```

## Claude Desktop Integration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

### Stdio Mode (Recommended)

```json
{
  "mcpServers": {
    "captain-search": {
      "command": "captain-search",
      "env": {
        "SERPER_API_KEY": "your_key_here",
        "BRAVE_API_KEY": "your_key_here"
      }
    }
  }
}
```

### Remote Server Mode

```json
{
  "mcpServers": {
    "captain-search": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

If you enabled `MCP_AUTH_TOKEN` and your client can't set headers, you can pass it
via query params:

```json
{
  "mcpServers": {
    "captain-search": {
      "url": "http://localhost:8000/mcp?api_key=your-secret-token"
    }
  }
}
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SERPER_API_KEY` | Serper.dev API key | At least one provider key |
| `BRAVE_API_KEY` | Brave Search API key | At least one provider key |
| `TAVILY_API_KEY` | Tavily API key | At least one provider key |
| `TAVILY_API_KEY_2` | Second Tavily key (for rotation) | Optional |
| `PERPLEXITY_API_KEY` | Perplexity API key | At least one provider key |
| `JINA_API_KEY` | Jina Reader API key | Optional |
| `SEARCH_TIMEOUT_SECONDS` | Request timeout (default: 30) | Optional |
| `MCP_AUTH_TOKEN` | Optional bearer token to protect the remote `/mcp` endpoint | Optional |

### Config File (Optional)

Create `config.yaml` to customize provider weights:

```yaml
providers:
  serper:
    weight: 42  # Higher = more likely to be selected
    enabled: true
  brave:
    weight: 33
    enabled: true
  tavily:
    weight: 17
    enabled: true
  perplexity:
    weight: 8
    enabled: true
```

Default weights are based on free tier limits:
- **Serper**: 42% (2,500/month)
- **Brave**: 33% (2,000/month)
- **Tavily**: 17% (1,000/month)
- **Perplexity**: 8% (limited)

## Provider Selection Logic

1. **Weighted Random Selection**: A provider is chosen randomly based on configured weights
2. **Automatic Fallback**: If the selected provider fails, others are tried in weight order
3. **Multi-Provider Mode**: `search_multi` queries all providers in parallel for comprehensive results

## Response Format

### Markdown (Default)

```markdown
# Search Results for: AI developments

*Providers used: serper | 234ms*

## 1. Article Title
**URL:** https://example.com/article

Article snippet or description...

*Source: serper*
```

### JSON

```json
{
  "query": "AI developments",
  "results": [
    {
      "title": "Article Title",
      "url": "https://example.com/article",
      "content": "Article snippet...",
      "source": "serper"
    }
  ],
  "providers_used": ["serper"],
  "elapsed_ms": 234
}
```

## Docker

```bash
# Build
docker build -t captain-search .

# Run
docker run -d -p 8000:8000 \
  -e SERPER_API_KEY=your_key \
  -e BRAVE_API_KEY=your_key \
  -e MCP_AUTH_TOKEN=your_secret_token \
  captain-search --transport http --port 8000
```

## Development

```bash
# Clone and install in dev mode
git clone https://github.com/yourusername/captain-search.git
cd captain-search
uv pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src/
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
