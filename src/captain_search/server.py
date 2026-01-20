"""FastMCP server for Captain Search."""

from __future__ import annotations

import sys
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from captain_search.auth import build_auth_provider
from captain_search.config import get_config
from captain_search.tools.code_search import search_code as code_impl
from captain_search.tools.fetch import fetch_webpage as fetch_impl
from captain_search.tools.search import search_web as web_impl

# Initialize config early to validate environment
config = get_config()

# Optional auth for remote MCP deployments
auth_provider = build_auth_provider(config.settings.mcp_auth_token)

# Create FastMCP server
mcp = FastMCP(
    name="captain_search",
    instructions="""
Captain Search MCP Server - Unified web and code search across multiple providers.

Available tools:
- search_web: Search the web using weighted selection with fallback
- search_code: Search code across Exa, grep.app, DeepWiki, and Noodl
- fetch_webpage: Fetch and extract content from a webpage or PDF

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

CODE_ANNOTATIONS = {
    "title": "Code Search",
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
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
        int,
        Field(
            description="Maximum number of results (1-50). In multi mode, per provider.",
            ge=1,
            le=50,
        ),
    ] = 10,
    provider: Annotated[
        str | None,
        Field(
            description=(
                "Provider selector: auto (default), multi/all, a provider name, or a comma-separated list."
            )
        ),
    ] = None,
) -> str:
    """
    Search the web using weighted selection or multi-provider search.

    Args:
        query: The search query string
        max_results: Maximum number of results (1-50, default 10). Per provider in multi mode.
        provider: Provider selector (default: auto)

    Returns:
        Search results in markdown format
    """
    provider_value = (provider or "auto").strip().lower()
    return await web_impl(
        query=query,
        max_results=max_results,
        provider=provider_value,
        format="markdown",
    )


@mcp.tool(name="fetch_webpage", annotations=FETCH_ANNOTATIONS)
async def fetch_webpage(
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
        - Fetch a webpage: fetch_webpage("https://example.com/article")
        - Fetch a PDF: fetch_webpage("https://example.com/document.pdf")
    """
    # Always use markdown format for agents
    return await fetch_impl(url=url, format="markdown")


@mcp.tool(name="search_code", annotations=CODE_ANNOTATIONS)
async def search_code(
    query: Annotated[
        str,
        Field(
            description="Code search query (e.g., function names, error messages, API usage)",
            min_length=1,
            max_length=500,
        ),
    ],
    repo: Annotated[
        str | None,
        Field(
            description=(
                "Git URL or owner/repo to scope results (e.g., 'facebook/react'). "
                "When provided, enables DeepWiki Q&A and Noodl graph search for that repo."
            )
        ),
    ] = None,
) -> str:
    """
    Search code across multiple providers.

    Args:
        query: Code search query string
        repo: Git URL or owner/repo (optional). When provided, results are scoped to this repo.

    Returns:
        Search results in markdown format
    """
    return await code_impl(query=query, repo=repo)


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
        print(
            "Warning: No search providers configured. Set API keys in environment.", file=sys.stderr
        )

    # Run server
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
