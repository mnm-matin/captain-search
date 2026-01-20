"""grep.app provider for searching code across GitHub repos."""

from __future__ import annotations

import httpx

from captain_search.providers.base import SearchProvider, SearchResult

GREP_APP_URL = "https://grep.app/api/search"


class GrepAppProvider(SearchProvider):
    """grep.app provider for searching code across GitHub."""

    name = "grep_app"

    def __init__(self, timeout: float = 30.0):
        super().__init__(api_key=None, timeout=timeout)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return await self.code_search(query, repo=None, max_results=max_results)

    async def code_search(
        self, query: str, repo: str | None = None, max_results: int = 10
    ) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(GREP_APP_URL, params={"q": query})
            response.raise_for_status()
            data = response.json()

        hits = data.get("hits", {}).get("hits", [])
        if repo:
            hits = [hit for hit in hits if hit.get("repo") == repo]

        results: list[SearchResult] = []
        for hit in hits[:max_results]:
            hit_repo = hit.get("repo", "")
            branch = hit.get("branch", "master")
            path = hit.get("path", "")
            url = f"https://github.com/{hit_repo}/blob/{branch}/{path}"
            snippet = hit.get("content", {}).get("snippet", "").strip()
            results.append(
                SearchResult(
                    title=f"{hit_repo}/{path}",
                    url=url,
                    content=snippet,
                    source=self.name,
                )
            )

        return results
