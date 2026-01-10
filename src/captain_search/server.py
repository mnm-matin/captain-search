"""FastMCP server for Captain Search."""

from __future__ import annotations

import sys
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from captain_search.auth import build_auth_provider
from captain_search.config import get_config
from captain_search.tools.fetch import search_fetch_webpage as fetch_impl
from captain_search.tools.search import search_multi as multi_impl
from captain_search.tools.search import search_web as web_impl

# Initialize config early to validate environment
config = get_config()

# Optional auth for remote MCP deployments
auth_provider = build_auth_provider(config.settings.mcp_auth_token)

# Create FastMCP server
mcp = FastMCP(
    name="captain_search",
    instructions="""
Captain Search MCP Server - Unified web search across multiple providers.

Available tools:
- search_web: Search the web using a single provider (weighted random selection with fallback)
- search_multi: Search all providers in parallel and combine results
- search_fetch_webpage: Fetch and extract content from a webpage or PDF

The server automatically selects providers based on configured weights and handles
failures by trying alternative providers.
""",
    auth=auth_provider,
)


# Tool annotations following MCP best practices
SEARCH_ANNOTATIONS = {
    "title": "Web Search",
    "readOnlyHint": True,  # Does not modify environment
    "destructiveHint": False,  # No destructive operations
    "idempotentHint": True,  # Same args = same result (mostly)
    "openWorldHint": True,  # Interacts with external services
}

FETCH_ANNOTATIONS = {
    "title": "Fetch Webpage",
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


@mcp.tool(name="search_web", annotations=SEARCH_ANNOTATIONS)
async def search_web(
    query: Annotated[str, Field(description="Search query", min_length=1, max_length=500)],
    max_results: Annotated[
        int, Field(description="Maximum number of results to return", ge=1, le=50)
    ] = 10,
) -> str:
    """
    Search the web using weighted random provider selection with automatic fallback.

    Searches across multiple providers (Serper, Brave, Tavily, Perplexity) using
    weighted random selection based on their free tier limits. If the selected
    provider fails, automatically tries the next provider.

    Args:
        query: The search query string
        max_results: Maximum number of results (1-50, default 10)

    Returns:
        Search results in markdown format
    """
    # Always use markdown format for agents (most token efficient)
    return await web_impl(query=query, max_results=max_results, format="markdown")


@mcp.tool(name="search_multi", annotations=SEARCH_ANNOTATIONS)
async def search_multi(
    query: Annotated[str, Field(description="Search query", min_length=1, max_length=500)],
    max_results_per_provider: Annotated[
        int, Field(description="Maximum results per provider", ge=1, le=20)
    ] = 5,
    providers: Annotated[
        list[str] | None,
        Field(description="Specific providers to use (default: all). Options: serper, brave, tavily, perplexity"),
    ] = None,
) -> str:
    """
    Search multiple providers in parallel and combine results.

    Queries all enabled providers simultaneously, combines the results,
    and optionally deduplicates by URL. Useful for comprehensive searches
    that need results from multiple sources.

    Args:
        query: The search query string
        max_results_per_provider: Max results from each provider (1-20, default 5)
        providers: Specific providers to use (default: all enabled)

    Returns:
        Combined search results in the specified format
    """
    # Hardcoded for optimal agent experience: always deduplicate, always markdown
    return await multi_impl(
        query=query,
        max_results_per_provider=max_results_per_provider,
        providers=providers,
        deduplicate=True,  # Always deduplicate for agents
        format="markdown",  # Always markdown (most token efficient)
    )


@mcp.tool(name="search_fetch_webpage", annotations=FETCH_ANNOTATIONS)
async def search_fetch_webpage(
    url: Annotated[str, Field(description="URL to fetch content from")],
) -> str:
    """
    Fetch and extract content from a webpage or PDF.

    Uses Jina Reader to fetch and convert web pages and PDFs to clean text.
    Handles JavaScript-rendered pages and extracts content from PDFs.

    Args:
        url: The URL to fetch (web page or PDF)

    Returns:
        Extracted content in markdown format

    Examples:
        - Fetch a webpage: search_fetch_webpage("https://example.com/article")
        - Fetch a PDF: search_fetch_webpage("https://example.com/document.pdf")
    """
    # Always use markdown format for agents
    return await fetch_impl(url=url, format="markdown")


def main():
    """Run the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Captain Search MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP/SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP/SSE transport (default: 0.0.0.0)",
    )

    args = parser.parse_args()

    # Show configured providers on startup
    enabled = config.get_enabled_providers()
    if enabled:
        print(f"Captain Search starting with providers: {', '.join(enabled)}", file=sys.stderr)
    else:
        print("Warning: No search providers configured. Set API keys in environment.", file=sys.stderr)

    # Run server
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
