"""Fetch tool for webpage/PDF extraction."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from captain_search.config import get_config
from captain_search.providers.jina import JinaProvider


class FetchFormat(str, Enum):
    """Output format options for fetch."""

    MARKDOWN = "markdown"
    TEXT = "text"


class FetchInput(BaseModel):
    """Input schema for fetch_webpage tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: str = Field(..., description="URL to fetch content from")
    format: FetchFormat = Field(
        default=FetchFormat.MARKDOWN, description="Output format (markdown or text)"
    )


async def fetch_webpage(
    url: str,
    format: str = "markdown",
) -> str:
    """
    Fetch and extract content from a webpage or PDF.

    Uses Jina Reader to fetch and convert web pages and PDFs to clean text.
    Handles JavaScript-rendered pages and extracts content from PDFs.

    Args:
        url: The URL to fetch (web page or PDF)
        format: Output format - "markdown" or "text" (default "markdown")

    Returns:
        Extracted content in the specified format, or error message

    Examples:
        - Fetch a webpage: fetch_webpage("https://example.com/article")
        - Fetch a PDF: fetch_webpage("https://example.com/document.pdf")
    """
    config = get_config()

    # Get Jina API key if available (optional, rate limited without)
    jina_config = config.providers.jina
    api_key = jina_config.api_key if jina_config.enabled else None

    provider = JinaProvider(api_key=api_key, timeout=60.0)

    try:
        response = await provider.fetch(url, format=format)

        if response.error:
            return f"**Error:** {response.error}"

        # Return clean content - no metadata overhead
        if response.title:
            return f"# {response.title}\n\n{response.content}"
        return response.content

    finally:
        await provider.close()
