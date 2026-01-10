"""Jina Reader provider for webpage/PDF extraction."""

from __future__ import annotations

import httpx

from captain_search.providers.base import FetchResponse

JINA_READER_URL = "https://r.jina.ai"


class JinaProvider:
    """Jina Reader provider for webpage and PDF extraction."""

    name = "jina"

    def __init__(self, api_key: str | None = None, timeout: float = 60.0):
        """
        Initialize Jina provider.

        Args:
            api_key: Optional Jina API key (works without, but rate limited to 20 RPM)
            timeout: Request timeout in seconds (default 60s for large documents)
        """
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create an HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def fetch(self, url: str, format: str = "markdown") -> FetchResponse:
        """
        Fetch and extract content from a URL.

        Jina Reader handles:
        - Regular web pages (HTML → Markdown)
        - PDF documents
        - Dynamic content (JavaScript rendered)

        Args:
            url: URL to fetch
            format: Output format ("markdown" or "text")

        Returns:
            FetchResponse with extracted content
        """
        import time

        start = time.monotonic()

        client = await self.get_client()

        # Jina Reader URL format: https://r.jina.ai/{url}
        reader_url = f"{JINA_READER_URL}/{url}"

        headers = {
            "Accept": "text/plain" if format == "text" else "text/markdown",
        }

        # Add API key if available (removes rate limits)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = await client.get(reader_url, headers=headers, follow_redirects=True)
            response.raise_for_status()

            content = response.text
            elapsed_ms = int((time.monotonic() - start) * 1000)

            # Try to extract title from markdown content
            title = ""
            if content.startswith("# "):
                first_line = content.split("\n")[0]
                title = first_line.lstrip("# ").strip()

            return FetchResponse(
                url=url,
                title=title,
                content=content,
                format=format,
                elapsed_ms=elapsed_ms,
            )

        except httpx.HTTPStatusError as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            error_msg = f"HTTP {e.response.status_code}"
            if e.response.status_code == 429:
                error_msg = "Rate limit exceeded (20 RPM without API key)"
            return FetchResponse(
                url=url,
                format=format,
                elapsed_ms=elapsed_ms,
                error=error_msg,
            )

        except httpx.TimeoutException:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return FetchResponse(
                url=url,
                format=format,
                elapsed_ms=elapsed_ms,
                error="Request timed out",
            )

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return FetchResponse(
                url=url,
                format=format,
                elapsed_ms=elapsed_ms,
                error=str(e),
            )
