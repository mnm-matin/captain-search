"""DeepWiki provider for repo-scoped Q&A via MCP."""

from __future__ import annotations

import json
import uuid

import httpx

from captain_search.providers.base import SearchProvider, SearchResult

DEEPWIKI_MCP_URL = "https://mcp.deepwiki.com/mcp"


class DeepWikiProvider(SearchProvider):
    name = "deepwiki"

    def __init__(self, timeout: float = 90.0):
        super().__init__(api_key=None, timeout=timeout)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return []

    async def _initialize_session(self, client: httpx.AsyncClient) -> str:
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "captain-search", "version": "1.0.0"},
            },
            "id": 1,
        }

        response = await client.post(
            DEEPWIKI_MCP_URL,
            json=payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        response.raise_for_status()

        session_id = response.headers.get("mcp-session-id")
        if not session_id:
            raise RuntimeError("DeepWiki session id missing")
        return session_id

    async def _call_tool(
        self, client: httpx.AsyncClient, session_id: str, tool_name: str, arguments: dict
    ) -> str:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": str(uuid.uuid4()),
        }

        response = await client.post(
            DEEPWIKI_MCP_URL,
            json=payload,
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
            },
        )
        response.raise_for_status()

        result: list[str] = []
        for line in response.text.split("\n"):
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if not data or data == "ping" or not data.startswith("{"):
                continue
            parsed = json.loads(data)
            content = parsed.get("result", {}).get("content", [])
            for item in content:
                if item.get("type") == "text":
                    result.append(item.get("text", ""))
        return "".join(result)

    async def ask_question(self, question: str, repo: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            session_id = await self._initialize_session(client)
            return await self._call_tool(
                client,
                session_id,
                "ask_question",
                {"repoName": repo, "question": question},
            )

