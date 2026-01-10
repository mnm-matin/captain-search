"""Brave Search provider."""

from __future__ import annotations

from captain_search.providers.base import SearchProvider, SearchResult

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveProvider(SearchProvider):
    """Brave Search provider."""

    name = "brave"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """
        Search using Brave Search API.

        Brave provides web search results via a GET API.
        Free tier: 2,000 queries/month, 1 req/sec rate limit.
        """
        if not self.api_key:
            raise ValueError("Brave API key is required")

        client = await self.get_client()

        headers = {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
        }

        params = {
            "q": query,
            "count": max_results,
        }

        response = await client.get(BRAVE_API_URL, headers=headers, params=params)
        response.raise_for_status()

        data = response.json()

        # Brave returns results in "web.results" path
        web_data = data.get("web", {})
        raw_results = web_data.get("results", [])

        return self._normalize_results(raw_results)

    def _normalize_results(self, raw_results: list[dict]) -> list[SearchResult]:
        """Normalize Brave results to standard format."""
        results = []
        for item in raw_results:
            try:
                result = SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("description", ""),
                    source=self.name,
                )
                if result.url:
                    results.append(result)
            except Exception:
                continue
        return results
