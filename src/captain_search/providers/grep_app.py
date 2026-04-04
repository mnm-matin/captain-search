"""grep.app provider for searching code across GitHub repos."""

from __future__ import annotations

import re
from collections.abc import Sequence

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from captain_search.providers.base import SearchProvider, SearchResult

GREP_APP_MCP_URL = "https://mcp.grep.app"
GREP_APP_TOOL_NAME = "searchGitHub"


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
        arguments: dict[str, object] = {
            "query": query,
            "useRegexp": False,
            "matchCase": False,
            "matchWholeWords": False,
        }
        if repo:
            arguments["repo"] = repo

        result = await self._call_tool(arguments)
        texts = self._result_texts(getattr(result, "content", None))
        if getattr(result, "isError", False):
            self._raise_mcp_error("\n\n".join(texts))

        results: list[SearchResult] = []
        for text in texts:
            results.extend(self._parse_search_results(text))
        return results[:max_results]

    async def _call_tool(self, arguments: dict[str, object]) -> object:
        client = await self.get_client()
        async with streamable_http_client(GREP_APP_MCP_URL, http_client=client) as streams:
            read_stream, write_stream, _session_id = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await session.call_tool(GREP_APP_TOOL_NAME, arguments)

    def _result_texts(self, content: Sequence[object] | None) -> list[str]:
        if not content:
            return []

        texts: list[str] = []
        for item in content:
            if getattr(item, "type", None) != "text":
                continue
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
        return texts

    def _raise_mcp_error(self, text: str) -> None:
        message = text.strip() or "grep.app MCP error"
        lowered = message.lower()
        if "too many request" in lowered or '"too many r' in lowered:
            request = httpx.Request("POST", GREP_APP_MCP_URL)
            rate_limited = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError(
                "Rate limit exceeded",
                request=request,
                response=rate_limited,
            )
        raise RuntimeError(message)

    def _parse_search_results(self, text: str) -> list[SearchResult]:
        blocks = [block.strip() for block in re.split(r"(?=Repository:\s)", text) if block.strip()]
        results: list[SearchResult] = []

        for block in blocks:
            normalized = re.sub(
                r"\s+(?=(Repository|Path|URL|License|Snippets):)",
                "\n",
                block,
            )
            repo_name = ""
            path = ""
            url = ""
            snippet_lines: list[str] = []
            in_snippets = False

            for raw_line in normalized.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("Repository:"):
                    repo_name = line.partition(":")[2].strip()
                    continue
                if line.startswith("Path:"):
                    path = line.partition(":")[2].strip()
                    continue
                if line.startswith("URL:"):
                    url = line.partition(":")[2].strip()
                    continue
                if line.startswith("Snippets:"):
                    in_snippets = True
                    continue
                if not in_snippets or line.startswith("--- Snippet"):
                    continue
                snippet_lines.append(raw_line.rstrip())

            if not url:
                continue

            results.append(
                SearchResult(
                    title=f"{repo_name}/{path}" if repo_name and path else path or repo_name or url,
                    url=url,
                    content="\n".join(snippet_lines).strip(),
                    source=self.name,
                )
            )

        return results
