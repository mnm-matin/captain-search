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
        api_key = self.choose_api_key(
            error_message=(
                "Perplexity API key is required. "
                "Set PERPLEXITY_API_KEY or PERPLEXITY_API_KEYS."
            ),
        )

        client = await self.get_client()

        headers = {
            "Authorization": f"Bearer {api_key}",
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

        return self._normalize_results(
            raw_results,
            content_keys=("snippet", "content"),
        )
