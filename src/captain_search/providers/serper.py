"""Serper (Google Search) provider."""

from __future__ import annotations

from captain_search.providers.base import SearchProvider, SearchResult

SERPER_API_URL = "https://google.serper.dev/search"


class SerperProvider(SearchProvider):
    """Serper.dev search provider (Google results)."""

    name = "serper"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """
        Search using Serper API.

        Serper provides Google search results via a simple POST API.
        Free tier: 2,500 searches/month.
        """
        api_key = self.choose_api_key(
            error_message="Serper API key is required. Set SERPER_API_KEY or SERPER_API_KEYS.",
        )

        client = await self.get_client()

        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "q": query,
            "num": max_results,
        }

        response = await client.post(SERPER_API_URL, headers=headers, json=payload)
        response.raise_for_status()

        data = response.json()

        # Serper returns results in "organic" key
        raw_results = data.get("organic", [])

        return self._normalize_results(
            raw_results,
            url_keys=("link",),
            content_keys=("snippet",),
        )
