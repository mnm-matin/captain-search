"""Tavily Search provider."""

from __future__ import annotations

import random

from captain_search.providers.base import SearchProvider, SearchResult

TAVILY_API_URL = "https://api.tavily.com/search"


class TavilyProvider(SearchProvider):
    """Tavily Search provider."""

    name = "tavily"

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: list[str] | None = None,
        timeout: float = 30.0,
    ):
        super().__init__(api_key=api_key, timeout=timeout)
        self.api_keys = api_keys or []
        if api_key and api_key not in self.api_keys:
            self.api_keys.append(api_key)

    def _get_api_key(self) -> str:
        """Get an API key (random selection if multiple available)."""
        if not self.api_keys:
            if self.api_key:
                return self.api_key
            raise ValueError("Tavily API key is required")
        return random.choice(self.api_keys)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """
        Search using Tavily API.

        Tavily provides AI-optimized search results via a POST API.
        Free tier: 1,000 searches/month per API key.
        """
        api_key = self._get_api_key()
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

    def _normalize_results(self, raw_results: list[dict]) -> list[SearchResult]:
        """Normalize Tavily results to standard format."""
        results = []
        for item in raw_results:
            try:
                result = SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    source=self.name,
                )
                if result.url:
                    results.append(result)
            except Exception:
                continue
        return results
