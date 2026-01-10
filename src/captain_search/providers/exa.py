"""Exa.ai Search provider via official API (requires API key)."""

from __future__ import annotations

import random

from captain_search.providers.base import SearchProvider, SearchResult

EXA_API_URL = "https://api.exa.ai/search"


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
        super().__init__(api_key=api_key, timeout=timeout)
        self.api_keys = api_keys or []
        if api_key and api_key not in self.api_keys:
            self.api_keys.append(api_key)

    def _get_api_key(self) -> str | None:
        """Get an API key (random selection if multiple available)."""
        if self.api_keys:
            return random.choice(self.api_keys)
        return self.api_key

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """
        Search using Exa.ai official API.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            
        Returns:
            List of SearchResult objects
        """
        api_key = self._get_api_key()
        if not api_key:
            raise ValueError("Exa API key is required. Set EXA_API_KEY or use exa_mcp provider.")

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
        return self._normalize_results(data.get("results", []))

    def _normalize_results(self, raw_results: list[dict]) -> list[SearchResult]:
        """Normalize raw Exa API results to standard format."""
        results = []
        for item in raw_results:
            try:
                result = SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("text", item.get("snippet", ""))[:500],
                    source=self.name,
                )
                if result.url:
                    results.append(result)
            except Exception:
                continue
        return results
