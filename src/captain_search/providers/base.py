"""Base provider interface and common types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field


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
    error: str | None = Field(default=None, description="Error message if search failed")


class FetchResponse(BaseModel):
    """Response from a webpage fetch operation."""

    model_config = ConfigDict(extra="ignore")

    url: str = Field(description="URL that was fetched")
    title: str = Field(default="", description="Page title")
    content: str = Field(default="", description="Extracted content")
    format: str = Field(default="markdown", description="Content format")
    elapsed_ms: int = Field(default=0, description="Time taken in milliseconds")
    error: str | None = Field(default=None, description="Error message if fetch failed")


class SearchProvider(ABC):
    """Abstract base class for search providers."""

    name: str = "base"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
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

    def _normalize_results(self, raw_results: list[dict[str, Any]]) -> list[SearchResult]:
        """Convert raw API results to SearchResult objects."""
        results = []
        for item in raw_results:
            try:
                result = SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url") or item.get("link", ""),
                    content=item.get("content") or item.get("snippet", ""),
                    source=self.name,
                )
                if result.url:  # Only include results with valid URLs
                    results.append(result)
            except Exception:
                continue  # Skip malformed results
        return results
