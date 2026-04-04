"""Tavily Search provider."""

from __future__ import annotations

import time

import httpx

from captain_search.providers.base import FetchResponse, SearchProvider, SearchResult

TAVILY_API_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_API_URL = "https://api.tavily.com/extract"


class TavilyProvider(SearchProvider):
    """Tavily Search provider."""

    name = "tavily"

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: list[str] | None = None,
        timeout: float = 30.0,
    ):
        super().__init__(api_key=api_key, api_keys=api_keys, timeout=timeout)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """
        Search using Tavily API.

        Tavily provides AI-optimized search results via a POST API.
        Free tier: 1,000 searches/month per API key.
        """
        api_key = self.choose_api_key(error_message="Tavily API key is required")
        client = await self.get_client()

        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }

        response = await client.post(TAVILY_API_URL, json=payload)
        response.raise_for_status()

        data = response.json()

        # Tavily returns results in "results" key
        raw_results = data.get("results", [])

        return self._normalize_results(raw_results)

    async def fetch(self, url: str, format: str = "markdown") -> FetchResponse:
        """Fetch webpage content using Tavily Extract."""
        api_key = self.choose_api_key(self.api_keys, error_message="Tavily API key is required")
        client = await self.get_client()
        start = time.monotonic()

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "urls": url,
            "format": format,
            "extract_depth": "basic",
            "include_images": False,
            "include_favicon": False,
        }

        try:
            response = await client.post(TAVILY_EXTRACT_API_URL, json=payload, headers=headers)
            response.raise_for_status()

            data = response.json()
            elapsed_ms = int((time.monotonic() - start) * 1000)
            raw_result = next(iter(data.get("results", [])), None)
            if isinstance(raw_result, dict):
                content = str(raw_result.get("raw_content") or "").strip()
                if content:
                    return FetchResponse(
                        url=str(raw_result.get("url") or url).strip() or url,
                        title=str(raw_result.get("title") or "").strip(),
                        content=content,
                        format=format,
                        status=response.status_code,
                        elapsed_ms=elapsed_ms,
                    )

            error_message = _extract_failed_result_error(data) or "Extraction returned empty content"
            return FetchResponse(
                url=url,
                format=format,
                status=response.status_code,
                elapsed_ms=elapsed_ms,
                error=error_message,
            )
        except httpx.HTTPStatusError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            error_message = f"HTTP {exc.response.status_code}"
            if exc.response.status_code == 429:
                error_message = "Rate limit exceeded"
            return FetchResponse(
                url=url,
                format=format,
                status=exc.response.status_code,
                elapsed_ms=elapsed_ms,
                error=error_message,
            )
        except httpx.TimeoutException:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return FetchResponse(
                url=url,
                format=format,
                elapsed_ms=elapsed_ms,
                error="Request timed out",
            )
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return FetchResponse(
                url=url,
                format=format,
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )


def _extract_failed_result_error(data: object) -> str | None:
    if not isinstance(data, dict):
        return None

    failed_results = data.get("failed_results")
    if not isinstance(failed_results, list) or not failed_results:
        return None

    failed_result = failed_results[0]
    if not isinstance(failed_result, dict):
        text = str(failed_result).strip()
        return text or None

    for key in ("error", "message", "detail", "details"):
        value = failed_result.get(key)
        text = str(value).strip() if value is not None else ""
        if text:
            return text

    status = failed_result.get("status") or failed_result.get("status_code")
    if status is not None:
        return str(status)

    return None
