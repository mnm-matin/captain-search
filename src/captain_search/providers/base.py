"""Base provider interface and common types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from captain_search.health import ProviderCooldownError, get_health_registry


class SearchResult(BaseModel):
    """A single search result."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(description="Title of the result")
    url: str = Field(description="URL of the result")
    content: str = Field(default="", description="Snippet or content of the result")
    source: str = Field(description="Provider that returned this result")


class SearchResponse(BaseModel):
    """Response from a search operation."""

    model_config = ConfigDict(extra="ignore")

    query: str = Field(description="Original search query")
    results: list[SearchResult] = Field(default_factory=list, description="Search results")
    providers_used: list[str] = Field(default_factory=list, description="Providers that were used")
    elapsed_ms: int = Field(default=0, description="Time taken in milliseconds")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings")
    error: str | None = Field(default=None, description="Error message if search failed")


class FetchResponse(BaseModel):
    """Response from a webpage fetch operation."""

    model_config = ConfigDict(extra="ignore")

    url: str = Field(description="URL that was fetched")
    title: str = Field(default="", description="Page title")
    content: str = Field(default="", description="Extracted content")
    format: str = Field(default="markdown", description="Content format")
    status: int | None = Field(default=None, description="HTTP status code when known")
    elapsed_ms: int = Field(default=0, description="Time taken in milliseconds")
    error: str | None = Field(default=None, description="Error message if fetch failed")


class SearchProvider(ABC):
    """Abstract base class for search providers."""

    name: str = "base"

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: Sequence[str] | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.api_keys = [value.strip() for value in (api_keys or []) if value and value.strip()]
        if self.api_key and self.api_key.strip() not in self.api_keys:
            self.api_keys.append(self.api_key.strip())
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._selected_api_key: str | None = None

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

    def choose_api_key(
        self,
        api_keys: Sequence[str] | None = None,
        *,
        error_message: str = "API key is required",
    ) -> str:
        candidates = [value.strip() for value in (api_keys or self.api_keys) if value and value.strip()]
        if self.api_key and self.api_key.strip() not in candidates:
            candidates.append(self.api_key.strip())
        if not candidates:
            raise ValueError(error_message)
        selected = get_health_registry().choose_api_key(
            self.name,
            candidates,
            error_message=error_message,
        )
        self._selected_api_key = selected
        return selected

    def record_success(self) -> None:
        """Reset health state after a successful provider call."""
        get_health_registry().record_success(self.name, api_key=self._selected_api_key)

    def record_http_error(self, error: httpx.HTTPStatusError) -> None:
        """Update health state after an HTTP failure."""
        get_health_registry().record_http_failure(
            self.name,
            status_code=error.response.status_code,
            retry_after=error.response.headers.get("Retry-After"),
            api_key=self._selected_api_key,
        )

    def record_transport_error(self, error: Exception) -> None:
        """Update health state after a timeout or transport failure."""
        if isinstance(error, ProviderCooldownError):
            return
        failure_kind = "timeout" if isinstance(error, httpx.TimeoutException) else "transport_error"
        get_health_registry().record_transport_failure(self.name, failure_kind=failure_kind)

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """
        Perform a search and return results.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects

        Raises:
            httpx.HTTPStatusError: If the API returns an error status
            httpx.TimeoutException: If the request times out
        """
        ...

    def _normalize_results(
        self,
        raw_results: Sequence[Mapping[str, Any]],
        *,
        title_keys: Sequence[str] = ("title",),
        url_keys: Sequence[str] = ("url", "link"),
        content_keys: Sequence[str] = ("content", "snippet", "text", "description"),
    ) -> list[SearchResult]:
        """Convert raw API results to SearchResult objects."""

        def first_value(item: Mapping[str, Any], keys: Sequence[str]) -> str:
            for key in keys:
                value = item.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    return text
            return ""

        results: list[SearchResult] = []
        for item in raw_results:
            title = first_value(item, title_keys)
            url = first_value(item, url_keys)
            if not url:
                continue
            content = first_value(item, content_keys)
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    content=content,
                    source=self.name,
                )
            )
        return results
