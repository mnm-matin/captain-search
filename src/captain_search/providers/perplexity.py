"""Perplexity Search provider."""

from __future__ import annotations

from captain_search.providers.base import SearchProvider, SearchResult

PERPLEXITY_API_URL = "https://api.perplexity.ai/search"


class PerplexityProvider(SearchProvider):
    """Perplexity Search provider."""

    name = "perplexity"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """
        Search using Perplexity API.

        Perplexity provides AI-powered search results.
        Requires Pro subscription (~$5/month credit).
        """
        if not self.api_key:
            raise ValueError("Perplexity API key is required")

        client = await self.get_client()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "query": query,
            "max_results": max_results,
        }

        response = await client.post(PERPLEXITY_API_URL, headers=headers, json=payload)
        response.raise_for_status()

        data = response.json()

        # Perplexity returns results in "results" key
        raw_results = data.get("results", [])

        return self._normalize_results(raw_results)

    def _normalize_results(self, raw_results: list[dict]) -> list[SearchResult]:
        """Normalize Perplexity results to standard format."""
        results = []
        for item in raw_results:
            try:
                result = SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("snippet") or item.get("content", ""),
                    source=self.name,
                )
                if result.url:
                    results.append(result)
            except Exception:
                continue
        return results
