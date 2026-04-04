"""Jina Reader provider for webpage/PDF extraction."""

from __future__ import annotations

import httpx

from captain_search.providers.base import FetchResponse, SearchProvider, SearchResult

JINA_READER_URL = "https://r.jina.ai"


class JinaProvider(SearchProvider):
    """Jina Reader provider for webpage and PDF extraction."""

    name = "jina"

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: list[str] | None = None,
        timeout: float = 60.0,
    ):
        """
        Initialize Jina provider.

        Args:
            api_key: Optional Jina API key (works without, but rate limited to 20 RPM)
            timeout: Request timeout in seconds (default 60s for large documents)
        """
        super().__init__(api_key=api_key, api_keys=api_keys, timeout=timeout)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        raise NotImplementedError("JinaProvider does not support web search.")

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

        selected_api_key = self.choose_api_key(error_message="Jina API key is required") if self.api_keys else None
        if selected_api_key:
            headers["Authorization"] = f"Bearer {selected_api_key}"

        try:
            response = await client.get(reader_url, headers=headers, follow_redirects=True)
            response.raise_for_status()

            content = response.text
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self.record_success()

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
                status=response.status_code,
                elapsed_ms=elapsed_ms,
            )

        except httpx.HTTPStatusError as e:
            self.record_http_error(e)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            error_msg = f"HTTP {e.response.status_code}"
            if e.response.status_code == 429:
                error_msg = "Rate limit exceeded (20 RPM without API key)"
            return FetchResponse(
                url=url,
                format=format,
                status=e.response.status_code,
                elapsed_ms=elapsed_ms,
                error=error_msg,
            )

        except httpx.TimeoutException as e:
            self.record_transport_error(e)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return FetchResponse(
                url=url,
                format=format,
                elapsed_ms=elapsed_ms,
                error="Request timed out",
            )

        except Exception as e:
            self.record_transport_error(e)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return FetchResponse(
                url=url,
                format=format,
                elapsed_ms=elapsed_ms,
                error=str(e),
            )
