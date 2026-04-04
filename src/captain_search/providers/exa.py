"""Exa.ai Search provider via official API (requires API key)."""

from __future__ import annotations

import time

import httpx

from captain_search.providers.base import FetchResponse, SearchProvider, SearchResult

EXA_API_URL = "https://api.exa.ai/search"
EXA_CONTENTS_API_URL = "https://api.exa.ai/contents"


class ExaProvider(SearchProvider):
    """Exa.ai Search provider using the official API.
    
    This provider requires an API key from https://exa.ai.
    For free usage without an API key, use ExaMcpProvider instead.
    """

    name = "exa"

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: list[str] | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize Exa API provider.
        
        Args:
            api_key: API key for Exa (required)
            api_keys: Optional list of API keys for rotation
            timeout: Request timeout in seconds
        """
        super().__init__(api_key=api_key, api_keys=api_keys, timeout=timeout)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """
        Search using Exa.ai official API.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            
        Returns:
            List of SearchResult objects
        """
        api_key = self.choose_api_key(
            error_message="Exa API key is required. Set EXA_API_KEY, EXA_API_KEYS, or use exa_mcp provider.",
        )

        client = await self.get_client()

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }

        payload = {
            "query": query,
            "numResults": max_results,
            "type": "auto",
            "useAutoprompt": True,
            "contents": {
                "text": {"maxCharacters": 500}
            }
        }

        response = await client.post(EXA_API_URL, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        return self._normalize_results(
            data.get("results", []),
            content_keys=("text", "snippet"),
        )

    async def fetch(self, url: str, format: str = "markdown") -> FetchResponse:
        """Fetch webpage content using Exa Contents."""
        api_key = self.choose_api_key(
            error_message="Exa API key is required. Set EXA_API_KEY, EXA_API_KEYS, or disable exa for fetch.",
        )
        client = await self.get_client()
        start = time.monotonic()

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }
        payload = {
            "urls": [url],
            "text": {
                "includeHtmlTags": False,
            },
        }

        try:
            response = await client.post(EXA_CONTENTS_API_URL, json=payload, headers=headers)
            response.raise_for_status()

            data = response.json()
            elapsed_ms = int((time.monotonic() - start) * 1000)
            raw_result = next(iter(data.get("results", [])), None)
            if isinstance(raw_result, dict):
                content = str(raw_result.get("text") or "").strip()
                if content:
                    self.record_success()
                    return FetchResponse(
                        url=str(raw_result.get("url") or url).strip() or url,
                        title=str(raw_result.get("title") or "").strip(),
                        content=content,
                        format=format,
                        status=response.status_code,
                        elapsed_ms=elapsed_ms,
                    )

            error_message = _extract_contents_error(data) or "Extraction returned empty content"
            return FetchResponse(
                url=url,
                format=format,
                status=response.status_code,
                elapsed_ms=elapsed_ms,
                error=error_message,
            )
        except httpx.HTTPStatusError as exc:
            self.record_http_error(exc)
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
        except httpx.TimeoutException as exc:
            self.record_transport_error(exc)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return FetchResponse(
                url=url,
                format=format,
                elapsed_ms=elapsed_ms,
                error="Request timed out",
            )
        except Exception as exc:
            self.record_transport_error(exc)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return FetchResponse(
                url=url,
                format=format,
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )


def _extract_contents_error(data: object) -> str | None:
    if not isinstance(data, dict):
        return None

    statuses = data.get("statuses")
    if not isinstance(statuses, list) or not statuses:
        return None

    status = statuses[0]
    if not isinstance(status, dict):
        text = str(status).strip()
        return text or None

    error = status.get("error")
    if isinstance(error, dict):
        tag = str(error.get("tag") or "").strip()
        http_status = error.get("httpStatusCode")
        if tag and http_status:
            return f"{tag} (HTTP {http_status})"
        if tag:
            return tag

    status_name = str(status.get("status") or "").strip()
    if status_name and status_name != "success":
        return status_name

    return None
