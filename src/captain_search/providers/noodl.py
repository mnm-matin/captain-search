"""Noodl provider for repo-scoped code search."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from captain_search.providers.base import SearchProvider, SearchResult
from captain_search.repo_utils import repo_name_from_path

NOODL_SEARCH_LIMIT = 10
REPO_CACHE_DIR = Path.home() / ".cache" / "captain-search" / "repos"
CLONE_REFRESH_SECONDS = 60  # Only pull updates if last fetch was > 60s ago


def _noodl_available() -> bool:
    return shutil.which("noodl") is not None


def _get_cache_path(full_name: str) -> Path:
    """Get the cache path for a repo."""
    safe_name = full_name.replace("/", "__")
    return REPO_CACHE_DIR / safe_name


def _get_last_fetch_time(repo_path: Path) -> float:
    """Get the timestamp of the last git fetch."""
    fetch_head = repo_path / ".git" / "FETCH_HEAD"
    if fetch_head.exists():
        return fetch_head.stat().st_mtime
    # Fall back to HEAD if FETCH_HEAD doesn't exist
    head = repo_path / ".git" / "HEAD"
    if head.exists():
        return head.stat().st_mtime
    return 0


def _should_update_repo(repo_path: Path) -> bool:
    """Check if repo should be updated (last fetch > CLONE_REFRESH_SECONDS ago)."""
    last_fetch = _get_last_fetch_time(repo_path)
    return (time.time() - last_fetch) > CLONE_REFRESH_SECONDS


def _clone_or_update_repo(full_name: str) -> Path | None:
    """Clone repo if not exists, or pull updates if stale."""
    cache_path = _get_cache_path(full_name)

    if cache_path.exists():
        # Only pull if last fetch was > CLONE_REFRESH_SECONDS ago
        if _should_update_repo(cache_path):
            subprocess.run(
                ["git", "-C", str(cache_path), "pull", "--ff-only"],
                check=False,
                capture_output=True,
                text=True,
            )
        return cache_path

    # Clone the repo
    clone_url = f"https://github.com/{full_name}.git"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", clone_url, str(cache_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return cache_path


def _ensure_analyzed(repo_path: Path) -> bool:
    """Ensure repo is analyzed by noodl. Fast and idempotent - noodl skips if unchanged."""
    result = subprocess.run(
        ["noodl", "analyze", str(repo_path)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


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

        repo_name = repo_name_from_path(repo_path)
        if not repo_name:
            return []

        # Ensure repo is analyzed (fast, idempotent)
        if not _ensure_analyzed(repo_path):
            return []

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

    def code_search_by_name(
        self,
        query: str,
        repo_full: str,
        max_results: int = NOODL_SEARCH_LIMIT,
    ) -> list[SearchResult]:
        """Search by repo name (owner/repo), auto-cloning if needed."""
        if not self.is_available():
            return []

        # Clone or update repo
        repo_path = _clone_or_update_repo(repo_full)
        if not repo_path:
            return []

        return self.code_search(query, repo_path, max_results)

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
