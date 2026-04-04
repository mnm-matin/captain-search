"""GitHub code search provider using gh CLI authentication."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any

import httpx

from captain_search.providers.base import SearchProvider, SearchResult

GITHUB_CODE_SEARCH_URL = "https://api.github.com/search/code"
GITHUB_API_VERSION = "2026-03-10"
GITHUB_TEXT_MATCH_ACCEPT = "application/vnd.github.text-match+json"


def _read_gh_token_sync(gh_path: str | None) -> str | None:
    if not gh_path:
        return None

    completed = subprocess.run(
        [gh_path, "auth", "token"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None

    token = completed.stdout.strip()
    return token or None


def get_gh_cli_auth_state(gh_path: str | None = None) -> tuple[bool, bool]:
    resolved = gh_path or shutil.which("gh")
    if not resolved:
        return False, False
    return True, bool(_read_gh_token_sync(resolved))


class GitHubCodeSearchProvider(SearchProvider):
    """GitHub code search provider backed by gh CLI authentication."""

    name = "github_code_search"

    def __init__(
        self,
        timeout: float = 30.0,
        *,
        gh_path: str | None = None,
        api_version: str = GITHUB_API_VERSION,
    ):
        super().__init__(api_key=None, timeout=timeout)
        self.gh_path = gh_path or shutil.which("gh")
        self.api_version = api_version
        self._gh_token: str | None = None

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return await self.code_search(query, repo=None, max_results=max_results)

    async def is_authenticated(self) -> bool:
        return bool(await self._get_gh_token())

    async def code_search(
        self,
        query: str,
        repo: str | None = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        token = await self._get_gh_token()
        if not token:
            raise RuntimeError("GitHub CLI is not authenticated. Run gh auth login.")

        client = await self.get_client()
        response = await client.get(
            GITHUB_CODE_SEARCH_URL,
            params={
                "q": self._build_query(query, repo),
                "per_page": max_results,
            },
            headers={
                "Accept": GITHUB_TEXT_MATCH_ACCEPT,
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": self.api_version,
            },
        )
        self._raise_for_status(response)

        payload = response.json()
        items = payload.get("items", [])
        if not isinstance(items, list):
            return []
        return self._parse_results(items)

    async def _get_gh_token(self) -> str | None:
        if self._gh_token:
            return self._gh_token
        if not self.gh_path:
            return None

        token = await asyncio.to_thread(_read_gh_token_sync, self.gh_path)
        if not token:
            return None
        self._gh_token = token
        return token

    def _build_query(self, query: str, repo: str | None) -> str:
        if not repo or f"repo:{repo}" in query:
            return query
        return f"{query} repo:{repo}"

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code in {403, 429} and self._is_rate_limited(response):
            rate_limited = httpx.Response(
                429,
                headers=response.headers,
                request=response.request,
            )
            raise httpx.HTTPStatusError(
                "Rate limit exceeded",
                request=response.request,
                response=rate_limited,
            )
        response.raise_for_status()

    def _is_rate_limited(self, response: httpx.Response) -> bool:
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining == "0":
            return True
        body = response.text.lower()
        return "rate limit" in body or "secondary rate limit" in body

    def _parse_results(self, items: list[Mapping[str, Any]]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("html_url") or "").strip()
            if not url:
                continue

            path = str(item.get("path") or "").strip()
            repository = item.get("repository")
            repo_full = ""
            if isinstance(repository, Mapping):
                repo_full = str(repository.get("full_name") or "").strip()

            title = url
            if repo_full and path:
                title = f"{repo_full}/{path}"
            elif path:
                title = path
            elif repo_full:
                title = repo_full

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    content=self._extract_snippet(item),
                    source=self.name,
                )
            )
        return results

    def _extract_snippet(self, item: Mapping[str, Any]) -> str:
        text_matches = item.get("text_matches")
        if not isinstance(text_matches, list):
            return ""

        snippets: list[str] = []
        seen: set[str] = set()
        for match in text_matches:
            if not isinstance(match, Mapping):
                continue
            fragment = str(match.get("fragment") or "").strip()
            if not fragment or fragment in seen:
                continue
            seen.add(fragment)
            snippets.append(fragment)

        return "\n".join(snippets)[:500]