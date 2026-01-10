"""Exa.ai Search provider via free MCP endpoint (no API key required)."""

from __future__ import annotations

import json

from captain_search.providers.base import SearchProvider, SearchResult

EXA_MCP_URL = "https://mcp.exa.ai/mcp"


class ExaMcpProvider(SearchProvider):
    """Exa.ai Search provider using the free MCP endpoint.
    
    This provider uses Exa's free MCP endpoint and does NOT require an API key.
    It's rate-limited but completely free to use.
    """

    name = "exa_mcp"

    def __init__(self, timeout: float = 30.0, **kwargs):
        """
        Initialize Exa MCP provider.
        
        Args:
            timeout: Request timeout in seconds
            **kwargs: Ignored (for compatibility)
        """
        # No API key required for MCP endpoint
        super().__init__(api_key=None, timeout=timeout)

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """
        Search using Exa.ai free MCP endpoint.

        Uses https://mcp.exa.ai/mcp - no authentication required.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            
        Returns:
            List of SearchResult objects
        """
        client = await self.get_client()

        # Build MCP JSON-RPC request
        mcp_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "web_search_exa",
                "arguments": {
                    "query": query,
                    "numResults": max_results,
                    "type": "auto",
                }
            },
            "id": 1,
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        response = await client.post(EXA_MCP_URL, json=mcp_request, headers=headers)
        response.raise_for_status()

        # Parse SSE response - Exa returns "event: message\ndata: {...}"
        text = response.text
        results = self._parse_mcp_response(text)

        return results

    async def code_search(self, query: str, tokens_num: int = 5000) -> list[SearchResult]:
        """
        Search for code-related context using Exa's code search.
        
        Args:
            query: Search query for code/API/SDK context
            tokens_num: Number of tokens to return (1000-50000)
            
        Returns:
            List of SearchResult objects
        """
        client = await self.get_client()

        mcp_request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "get_code_context_exa",
                "arguments": {
                    "query": query,
                    "tokensNum": tokens_num,
                }
            },
            "id": 1,
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        response = await client.post(EXA_MCP_URL, json=mcp_request, headers=headers)
        response.raise_for_status()

        results = self._parse_mcp_response(response.text)
        return results

    def _parse_mcp_response(self, text: str) -> list[SearchResult]:
        """Parse the SSE response from Exa MCP endpoint."""
        results = []
        
        # Find the JSON data in the SSE response
        # Format is: "event: message\ndata: {...}"
        for line in text.split("\n"):
            if line.startswith("data: "):
                json_str = line[6:]  # Remove "data: " prefix
                try:
                    data = json.loads(json_str)
                    # Extract content from MCP response
                    content = data.get("result", {}).get("content", [])
                    for item in content:
                        if item.get("type") == "text":
                            text_content = item.get("text", "")
                            results.extend(self._parse_search_results(text_content))
                except json.JSONDecodeError:
                    continue

        return results

    def _parse_search_results(self, text: str) -> list[SearchResult]:
        """Parse individual search results from Exa's text response."""
        results = []
        
        # Check if this is code context format (## headers with URLs below)
        # Only check the first 100 chars to avoid false positives from page content
        first_chunk = text[:100]
        if first_chunk.startswith("##") or "\n## " in first_chunk:
            return self._parse_code_context_results(text)
        
        # Standard web search format: Title:, URL:, Text: blocks
        current_result = {}
        lines = text.split("\n")
        
        for line in lines:
            line = line.strip()
            if line.startswith("Title:"):
                # Save previous result if exists
                if current_result.get("url"):
                    results.append(SearchResult(
                        title=current_result.get("title", ""),
                        url=current_result.get("url", ""),
                        content=current_result.get("content", "")[:500],  # Limit content
                        source=self.name,
                    ))
                current_result = {"title": line[6:].strip()}
            elif line.startswith("URL:"):
                current_result["url"] = line[4:].strip()
            elif line.startswith("Text:"):
                current_result["content"] = line[5:].strip()
            elif "content" in current_result and current_result.get("content"):
                # Append to content if we're in a text block
                current_result["content"] += " " + line

        # Don't forget the last result
        if current_result.get("url"):
            results.append(SearchResult(
                title=current_result.get("title", ""),
                url=current_result.get("url", ""),
                content=current_result.get("content", "")[:500],
                source=self.name,
            ))

        return results

    def _parse_code_context_results(self, text: str) -> list[SearchResult]:
        """Parse code context results with ## headers and code blocks."""
        import re
        results = []
        
        # Split by ## headers
        sections = re.split(r'\n## ', text)
        
        for section in sections:
            if not section.strip():
                continue
            
            lines = section.strip().split("\n")
            if not lines:
                continue
            
            # First line is the title (may have leading ##)
            title = lines[0].lstrip("#").strip()
            
            # Look for URL (usually on the next line, starts with http)
            url = ""
            content_lines = []
            in_code_block = False
            
            for line in lines[1:]:
                stripped = line.strip()
                if stripped.startswith("http"):
                    url = stripped
                elif stripped == "```":
                    in_code_block = not in_code_block
                elif in_code_block or stripped:
                    content_lines.append(line)
            
            if url and title:
                content = "\n".join(content_lines)[:500] if content_lines else ""
                results.append(SearchResult(
                    title=title,
                    url=url,
                    content=content,
                    source=self.name,
                ))
        
        return results
