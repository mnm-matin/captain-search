"""Tool-level regression tests for code search orchestration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from captain_search.tools.code_search import search_code
from tests._helpers import patch_code_search_backends, search_result

REPO_FULL = "mnm-matin/captain-search"
REPO_PATH = Path("/tmp/captain-search")
BASE_URL = f"https://github.com/{REPO_FULL}/blob/main"
DEEPWIKI_ANSWER = "Captain Search exposes web, code, and fetch tools through one MCP server."


def test_all_sections_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_code_search_backends(
        monkeypatch,
        repo_full=REPO_FULL,
        repo_path=REPO_PATH,
        local=[
            search_result(
                title="src/captain_search/server.py:10",
                url="file:///tmp/captain-search/src/captain_search/server.py#L10",
                content="def main(argv: Sequence[str] | None = None) -> int:",
                source="local_exact",
            )
        ],
        exa=[
            search_result(
                title="src/captain_search/server.py",
                url=f"{BASE_URL}/src/captain_search/server.py",
                content="def main(argv: Sequence[str] | None = None) -> int:",
                source="exa_mcp",
            )
        ],
        github=object(),
        github_search=[
            search_result(
                title="src/captain_search/tools/search.py",
                url=f"{BASE_URL}/src/captain_search/tools/search.py",
                content="async def search_web(query: str, max_results: int = 10) -> str:",
                source="github_code_search",
            )
        ],
        grep=[
            search_result(
                title="src/captain_search/rendering.py",
                url=f"{BASE_URL}/src/captain_search/rendering.py",
                content="def format_search_markdown(response: SearchResponse) -> str:",
                source="grep_app",
            )
        ],
        deepwiki=DEEPWIKI_ANSWER,
    )

    output = asyncio.run(search_code(query="search_web", repo=REPO_FULL))

    assert "## Local Exact Matches" in output
    assert "## Exa Code Context" in output
    assert "## GitHub Code Search" in output
    assert "## grep.app" in output
    assert "## DeepWiki" in output


def test_cooldown_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class CoolingRegistry:
        def is_provider_cooling(self, provider: str) -> bool:
            return provider in {"exa_mcp", "grep_app"}

    patch_code_search_backends(
        monkeypatch,
        health_registry=CoolingRegistry(),
    )

    output = asyncio.run(search_code(query="contextmanager"))

    assert "## Exa Code Context" in output
    assert "Set EXA_API_KEY or EXA_API_KEYS" in output
    assert "## grep.app" in output
    assert "pass --repo to enable repo-scoped providers" in output


def test_json_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_code_search_backends(
        monkeypatch,
        repo_full=REPO_FULL,
        repo_path=REPO_PATH,
        exa=[
            search_result(
                title="src/captain_search/server.py",
                url=f"{BASE_URL}/src/captain_search/server.py",
                content="def main(argv: Sequence[str] | None = None) -> int:",
                source="exa_mcp",
            )
        ],
        grep=RuntimeError("Rate limit exceeded"),
        deepwiki=DEEPWIKI_ANSWER,
        local=[],
    )

    output = asyncio.run(search_code(query="search_web", repo=REPO_FULL, format="json"))

    payload = json.loads(output)
    sections_by_source = {section["source"]: section for section in payload["sections"]}
    grep_error = next(error for error in payload["errors"] if "grep" in error["source"])

    assert payload["query"] == "search_web"
    assert payload["repo"]["full_name"] == REPO_FULL
    assert payload["repo"]["local_path"] == str(REPO_PATH)
    assert sections_by_source["exa_mcp"]["type"] == "matches"
    assert sections_by_source["exa_mcp"]["items"][0]["title"] == "src/captain_search/server.py"
    assert sections_by_source["deepwiki"]["type"] == "answer"
    assert sections_by_source["deepwiki"]["content"] == DEEPWIKI_ANSWER
    assert "Rate limit exceeded on grep.app." in grep_error["message"]


def test_filters_wrong_repo_results(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_code_search_backends(
        monkeypatch,
        repo_full=REPO_FULL,
        repo_path=REPO_PATH,
        exa=[
            search_result(
                title="Wrong repo",
                url="https://github.com/other/repo/blob/main/file.py",
                content="off repo",
                source="exa_mcp",
            )
        ],
        local=[],
    )

    output = asyncio.run(search_code(query="telemetry logging", repo=REPO_FULL))

    assert output == "No results found."


def test_local_exact_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    patch_code_search_backends(
        monkeypatch,
        repo_full=REPO_FULL,
        repo_path=repo_path,
        deepwiki="Repository not found",
        local=[
            search_result(
                title="src/captain_search/rendering.py:109",
                url="file:///tmp/repo/src/captain_search/rendering.py#L109",
                content="def format_search_markdown(response: SearchResponse) -> str:",
                source="local_exact",
            )
        ],
    )

    output = asyncio.run(search_code(query="format_search_markdown", repo=REPO_FULL))

    assert "## Local Exact Matches" in output
    assert "format_search_markdown" in output


def test_provider_errors_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_code_search_backends(
        monkeypatch,
        repo_full=REPO_FULL,
        repo_path=REPO_PATH,
        deepwiki="Repository not found",
        local=[],
    )

    output = asyncio.run(search_code(query="search_web", repo=REPO_FULL))

    assert "## DeepWiki" in output
    assert "Repository not indexed on DeepWiki." in output