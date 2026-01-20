"""Unified code search tool for MCP server."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from captain_search.providers import DeepWikiProvider, ExaMcpProvider, GrepAppProvider, NoodlProvider
from captain_search.providers.base import SearchResult

EXA_CODE_TOKENS_NUM = 50000
REPO_CACHE_DIR = Path.home() / ".cache" / "captain-search" / "repos"


def _parse_repo(repo: str) -> tuple[str, str]:
    repo = repo.strip()
    if repo.startswith(("/", "./", "../", "~")):
        raise ValueError("repo must be a git URL or owner/repo")

    if repo.startswith("git@"):
        host_part, path = repo.split(":", 1)
        host = host_part.split("@", 1)[1]
    elif repo.startswith(("http://", "https://")):
        parsed = urlparse(repo)
        host = parsed.netloc
        path = parsed.path
    else:
        host = "github.com"
        path = repo

    parts = path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError("repo must be in owner/repo format")
    owner, name = parts[0], parts[1].removesuffix(".git")
    full_name = f"{owner}/{name}"
    clone_url = f"https://{host}/{owner}/{name}.git"
    return full_name, clone_url


def _get_cache_path(full_name: str) -> Path:
    safe_name = full_name.replace("/", "__")
    return REPO_CACHE_DIR / safe_name


def _clone_repo(full_name: str, clone_url: str) -> Path:
    cache_path = _get_cache_path(full_name)
    if cache_path.exists():
        return cache_path

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", clone_url, str(cache_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return cache_path


def _format_results_section(title: str, results: list[SearchResult]) -> str:
    if not results:
        return ""

    lines = [f"## {title}"]
    for i, result in enumerate(results, 1):
        lines.append(f"### {i}. {result.title}")
        lines.append(f"**URL:** {result.url}")
        if result.content:
            content = result.content[:500] + "..." if len(result.content) > 500 else result.content
            lines.append(f"\n{content}\n")
        else:
            lines.append("")
    return "\n".join(lines).strip()


async def _exa_code_search(query: str, repo_full: str | None) -> list[SearchResult]:
    exa_query = f"{query} repo:{repo_full}" if repo_full else query

    provider = ExaMcpProvider(timeout=60.0)
    try:
        return await provider.code_search(exa_query, tokens_num=EXA_CODE_TOKENS_NUM)
    finally:
        await provider.close()


async def _deepwiki_search(query: str, repo_full: str) -> str:
    provider = DeepWikiProvider(timeout=90.0)
    try:
        return await provider.ask_question(query, repo_full)
    finally:
        await provider.close()


async def _grep_app_search(query: str, repo_full: str | None) -> list[SearchResult]:
    provider = GrepAppProvider(timeout=30.0)
    try:
        return await provider.code_search(query, repo=repo_full, max_results=10)
    finally:
        await provider.close()


def _noodl_search(query: str, repo_path: Path) -> list[SearchResult]:
    provider = NoodlProvider()
    if not provider.is_available():
        return []
    return provider.code_search(query, repo_path, max_results=10)


async def search_code(query: str, repo: str | None = None) -> str:
    repo_full = None
    repo_path = None
    if repo:
        repo_full, clone_url = _parse_repo(repo)
        repo_path = await asyncio.to_thread(_clone_repo, repo_full, clone_url)

    sections: list[str] = []

    exa_results = await _exa_code_search(query, repo_full)
    exa_section = _format_results_section("Exa Code Context", exa_results)
    if exa_section:
        sections.append(exa_section)

    if repo_full:
        deepwiki_answer = await _deepwiki_search(query, repo_full)
        if deepwiki_answer:
            sections.append(f"## DeepWiki\n{deepwiki_answer}")

    grep_results = await _grep_app_search(query, repo_full)
    grep_section = _format_results_section("grep.app", grep_results)
    if grep_section:
        sections.append(grep_section)

    if repo_path:
        noodl_results = await asyncio.to_thread(_noodl_search, query, repo_path)
        noodl_section = _format_results_section("Noodl", noodl_results)
        if noodl_section:
            sections.append(noodl_section)

    if not sections:
        return "No results found."

    return "\n\n".join(sections).strip()
