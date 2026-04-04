"""Parallel.ai Search and Extract provider."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import httpx

from captain_search.providers.base import FetchResponse, SearchProvider, SearchResult

PARALLEL_SEARCH_API_URL = "https://api.parallel.ai/v1beta/search"
PARALLEL_EXTRACT_API_URL = "https://api.parallel.ai/v1beta/extract"
PARALLEL_SEARCH_MODE = "agentic"
PARALLEL_EXCERPT_CHARS = 4000


class ParallelProvider(SearchProvider):
    """Parallel.ai provider for web search and webpage extraction."""

    name = "parallel"

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: Sequence[str] | None = None,
        timeout: float = 30.0,
    ):
        super().__init__(api_key=api_key, api_keys=api_keys, timeout=timeout)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search using Parallel Search."""
        api_key = self.choose_api_key(
            error_message="Parallel API key is required. Set PARALLEL_API_KEY or PARALLEL_API_KEYS.",
        )
        client = await self.get_client()

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }
        payload = {
            "objective": query,
            "search_queries": [query],
            "mode": PARALLEL_SEARCH_MODE,
            "max_results": max_results,
            "excerpts": {"max_chars_per_result": PARALLEL_EXCERPT_CHARS},
        }

        response = await client.post(PARALLEL_SEARCH_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

        results: list[SearchResult] = []
        for item in data.get("results", []):
            url = _clean_text(item.get("url"))
            if not url:
                continue
            excerpts = _string_list(item.get("excerpts"))
            results.append(
                SearchResult(
                    title=_clean_text(item.get("title")),
                    url=url,
                    content="\n\n".join(excerpts),
                    source=self.name,
                )
            )
        return results

    async def fetch(self, url: str, format: str = "markdown") -> FetchResponse:
        """Extract webpage content using Parallel Extract."""
        api_key = self.choose_api_key(
            error_message="Parallel API key is required. Set PARALLEL_API_KEY or PARALLEL_API_KEYS.",
        )
        client = await self.get_client()
        start = time.monotonic()

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }
        payload = {
            "urls": [url],
            "excerpts": False,
            "full_content": True,
        }

        try:
            response = await client.post(PARALLEL_EXTRACT_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            elapsed_ms = int((time.monotonic() - start) * 1000)

            raw_result = next(iter(data.get("results", [])), None)
            if raw_result is not None:
                content = _clean_text(raw_result.get("full_content"))
                if not content:
                    content = "\n\n".join(_string_list(raw_result.get("excerpts")))
                if content:
                    self.record_success()
                return FetchResponse(
                    url=_clean_text(raw_result.get("url")) or url,
                    title=_clean_text(raw_result.get("title")),
                    content=content,
                    format=format,
                    status=response.status_code,
                    elapsed_ms=elapsed_ms,
                )

            error_message = _extract_error_message(data.get("errors")) or "Extraction returned empty content"
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
            return FetchResponse(
                url=url,
                format=format,
                status=exc.response.status_code,
                elapsed_ms=elapsed_ms,
                error=f"HTTP {exc.response.status_code}",
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


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text:
            items.append(text)
    return items


def _extract_error_message(errors: Any) -> str | None:
    if not isinstance(errors, list) or not errors:
        return None
    first_error = errors[0]
    if not isinstance(first_error, dict):
        return _clean_text(first_error) or None

    content = _clean_text(first_error.get("content"))
    if content:
        return content

    error_type = _clean_text(first_error.get("error_type"))
    http_status = first_error.get("http_status_code")
    if error_type and http_status:
        return f"{error_type} (HTTP {http_status})"
    if error_type:
        return error_type
    return None