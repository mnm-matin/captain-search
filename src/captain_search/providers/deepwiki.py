"""DeepWiki provider for repo-scoped Q&A via MCP."""

from __future__ import annotations

import httpx

from captain_search.providers.base import SearchProvider, SearchResult
from captain_search.providers.mcp import extract_mcp_text_content

DEEPWIKI_MCP_URL = "https://mcp.deepwiki.com/mcp"


class DeepWikiProvider(SearchProvider):
    name = "deepwiki"

    def __init__(self, timeout: float = 90.0):
        super().__init__(api_key=None, timeout=timeout)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return []

    async def _call_tool(
        self, client: httpx.AsyncClient, tool_name: str, arguments: dict
    ) -> str:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": 1,
        }

        response = await client.post(
            DEEPWIKI_MCP_URL,
            json=payload,
            headers={"Accept": "text/event-stream, application/json"},
        )
        response.raise_for_status()
        texts = extract_mcp_text_content(response.text)
        return "\n\n".join(texts)

    async def ask_question(self, question: str, repo: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await self._call_tool(
                client,
                "ask_question",
                {"repoName": repo, "question": question},
            )

