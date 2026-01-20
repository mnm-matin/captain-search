"""Noodl provider for repo-scoped code search."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from captain_search.providers.base import SearchProvider, SearchResult

NOODL_SEARCH_LIMIT = 10


def _repo_name_from_path(repo_path: Path) -> str:
    name = repo_path.name
    if "__" in name:
        return name.replace("__", "/")
    return name


def _noodl_available() -> bool:
    return shutil.which("noodl") is not None


class NoodlProvider(SearchProvider):
    name = "noodl"

    def __init__(self, timeout: float = 30.0):
        super().__init__(api_key=None, timeout=timeout)
        self._available = _noodl_available()

    def is_available(self) -> bool:
        return self._available

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return []

    def code_search(
        self,
        query: str,
        repo_path: Path,
        max_results: int = NOODL_SEARCH_LIMIT,
    ) -> list[SearchResult]:
        if not self.is_available():
            return []

        repo_name = _repo_name_from_path(repo_path)
        result = subprocess.run(
            [
                "noodl",
                "search",
                query,
                repo_name,
                "--limit",
                str(max_results),
                "--include-content",
                "--format",
                "json",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return []

        return self._parse_results(result.stdout)

    def _parse_results(self, output: str) -> list[SearchResult]:
        data = json.loads(output)
        results: list[SearchResult] = []

        for process in data.get("results", []):
            for symbol in process.get("symbols", []):
                name = symbol.get("name", "")
                file_path = symbol.get("file_path", "")
                symbol_type = symbol.get("symbol_type", "")
                content = symbol.get("content", "")
                if not name or not file_path:
                    continue
                title = f"{symbol_type}: {name}" if symbol_type else name
                results.append(
                    SearchResult(
                        title=title,
                        url=f"file://{file_path}",
                        content=content[:500] if content else "",
                        source=self.name,
                    )
                )

        return results
