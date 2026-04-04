"""Unified code search tool for MCP server."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from captain_search.config import get_config
from captain_search.health import get_health_registry
from captain_search.providers import (
    DeepWikiProvider,
    ExaMcpProvider,
    GitHubCodeSearchProvider,
    GrepAppProvider,
    MorphWarpGrepProvider,
    NoodlProvider,
)
from captain_search.providers.base import SearchResult
from captain_search.rendering import (
    clean_deepwiki_answer,
    dedupe_results,
    format_error_section,
    format_results_section,
    prepare_code_results,
)
from captain_search.repo_utils import infer_repo_full, parse_repo, resolve_local_repo
from captain_search.telemetry import fail_tool_call, finish_tool_call, log_event, start_tool_call

EXA_CODE_TOKENS_NUM = 50000
REPO_CACHE_DIR = Path.home() / ".cache" / "captain-search" / "repos"
MORPH_TIMEOUT_SECONDS = 120.0
DEEPWIKI_TIMEOUT_SECONDS = 60.0
LOCAL_EXACT_TIMEOUT_SECONDS = 10.0
LOCAL_EXACT_RESULT_LIMIT = 6
NOODL_SEARCH_ENABLED = False
_LOCAL_QUERY_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}")
_LOCAL_QUERY_STOPWORDS = {
    "code",
    "context",
    "content",
    "data",
    "dependency",
    "docs",
    "guide",
    "link",
    "package",
    "query",
    "repo",
    "result",
    "results",
    "role",
    "search",
    "tool",
    "version",
    "workspace",
}

_CODE_SECTION_METADATA = {
    "local_exact": {"title": "Local Exact Matches", "source": "local_exact", "type": "matches"},
    "exa": {"title": "Exa Code Context", "source": "exa_mcp", "type": "matches"},
    "deepwiki": {"title": "DeepWiki", "source": "deepwiki", "type": "answer"},
    "github": {
        "title": "GitHub Code Search",
        "source": "github_code_search",
        "type": "matches",
    },
    "grep": {"title": "grep.app", "source": "grep_app", "type": "matches"},
    "morph": {"title": "Morph Warp Grep", "source": "morph_warp_grep", "type": "matches"},
    "noodl": {"title": "Noodl", "source": "noodl", "type": "matches"},
}


def _code_repo_metadata(
    repo_input: str | None,
    repo_full: str | None,
    repo_path: Path | None,
) -> dict[str, str | None]:
    return {
        "input": repo_input,
        "full_name": repo_full,
        "local_path": str(repo_path) if repo_path is not None else None,
    }


def _build_code_matches_section(key: str, results: list[SearchResult]) -> dict[str, object] | None:
    metadata = _CODE_SECTION_METADATA[key]
    items = [
        {
            "title": result.title,
            "url": result.url,
            "content": result.content,
        }
        for result in prepare_code_results(results)
    ]
    if not items:
        return None
    return {
        "type": metadata["type"],
        "source": metadata["source"],
        "title": metadata["title"],
        "items": items,
    }


def _build_code_answer_section(key: str, content: str) -> dict[str, object] | None:
    cleaned = content.strip()
    if not cleaned:
        return None
    metadata = _CODE_SECTION_METADATA[key]
    return {
        "type": metadata["type"],
        "source": metadata["source"],
        "title": metadata["title"],
        "content": cleaned,
    }


def _append_code_error(errors: list[dict[str, str]], key: str, message: str | None) -> None:
    if not message:
        return
    errors.append(
        {
            "source": str(_CODE_SECTION_METADATA[key]["source"]),
            "message": message,
        }
    )


def _render_code_search_json(
    *,
    query: str,
    repo: dict[str, str | None],
    sections: list[dict[str, object]],
    errors: list[dict[str, str]],
    error: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "query": query,
        "repo": repo,
        "sections": sections,
        "warnings": [],
        "errors": errors,
    }
    if error:
        payload["error"] = error
    return json.dumps(payload, indent=2)


def _resolve_repo(repo: str) -> tuple[str | None, Path | None]:
    repo = repo.strip()
    if not repo:
        return None, None

    local_path = resolve_local_repo(repo)
    if local_path:
        repo_full = infer_repo_full(local_path)
        log_event(
            "repo_resolved",
            repo_input=repo,
            repo_full=repo_full,
            repo_path=local_path,
            resolution="local",
        )
        return repo_full, local_path

    repo_full, clone_url = parse_repo(repo)
    log_event(
        "repo_resolved",
        repo_input=repo,
        repo_full=repo_full,
        clone_url=clone_url,
        resolution="remote",
    )
    repo_path = _clone_repo(repo_full, clone_url)
    return repo_full, repo_path


def _get_cache_path(full_name: str) -> Path:
    safe_name = full_name.replace("/", "__")
    return REPO_CACHE_DIR / safe_name


def _clone_repo(full_name: str, clone_url: str) -> Path:
    cache_path = _get_cache_path(full_name)
    if cache_path.exists():
        log_event(
            "repo_cache_hit",
            repo_full=full_name,
            repo_path=cache_path,
            clone_url=clone_url,
        )
        # Pull latest if already cloned
        subprocess.run(
            ["git", "-C", str(cache_path), "pull", "--ff-only"],
            check=False,  # Don't fail if pull fails (e.g., detached HEAD)
            capture_output=True,
            text=True,
        )
        return cache_path

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    log_event(
        "repo_clone",
        repo_full=full_name,
        repo_path=cache_path,
        clone_url=clone_url,
    )
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(cache_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(f"Failed to clone {full_name}: {detail}") from exc
    return cache_path


def _is_repo_relevant_url(url: str, repo_full: str) -> bool:
    return (
        repo_full in url
        or f"/{repo_full}/" in url
        or f"raw.githubusercontent.com/{repo_full}/" in url
    )


def _filter_repo_results(results: list[SearchResult], repo_full: str | None) -> list[SearchResult]:
    if not repo_full:
        return results
    return [result for result in results if _is_repo_relevant_url(result.url, repo_full)]


def _clean_provider_error(provider: str, error: str | None) -> str | None:
    if not error:
        return None
    cleaned = error.strip()
    if provider == "deepwiki" and "Repository not found" in cleaned:
        return "Repository not indexed on DeepWiki."
    if provider == "exa_mcp" and cleaned == "Rate limit exceeded":
        return (
            "Rate limit exceeded on Exa MCP. Set EXA_API_KEY or EXA_API_KEYS to authenticate "
            "requests."
        )
    if provider == "exa_mcp" and "Temporarily cooling down" in cleaned:
        return (
            "Exa MCP is temporarily cooling down after rate limits. Set EXA_API_KEY or "
            "EXA_API_KEYS to authenticate requests."
        )
    if provider == "grep_app" and cleaned == "Rate limit exceeded":
        return (
            "Rate limit exceeded on grep.app. Try again later or pass --repo to enable "
            "repo-scoped providers."
        )
    if provider == "grep_app" and "Temporarily cooling down" in cleaned:
        return (
            "grep.app is temporarily cooling down after rate limits. Try again later or pass "
            "--repo to enable repo-scoped providers."
        )
    if provider == "github_code_search" and cleaned == "Rate limit exceeded":
        return "Rate limit exceeded on GitHub Code Search. Try again later."
    if provider == "github_code_search" and cleaned == "HTTP 401":
        return "GitHub Code Search requires an authenticated gh CLI session. Run gh auth login."
    return cleaned


def _extract_local_query_terms(query: str) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []

    for quote_pattern in (r'"([^"]+)"', r"'([^']+)'"):
        for match in re.findall(quote_pattern, query):
            term = match.strip()
            normalized = term.lower()
            if len(term) < 3 or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)

    tokens: list[str] = []
    for token in _LOCAL_QUERY_TERM_RE.findall(query):
        normalized = token.lower().strip("._-")
        if len(normalized) < 4 or normalized in _LOCAL_QUERY_STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(token)

    tokens.sort(key=lambda token: (any(ch in token for ch in "._-"), len(token)), reverse=True)
    terms.extend(tokens)
    return terms[:5]


def _local_result_url(path: Path, line_number: str) -> str:
    return f"file://{path.resolve().as_posix()}#L{line_number}"


def _local_exact_search(query: str, repo_path: Path) -> list[SearchResult]:
    if not repo_path.exists():
        return []

    rg_path = shutil.which("rg")
    if not rg_path:
        return []

    terms = _extract_local_query_terms(query)
    if not terms:
        return []

    results: list[SearchResult] = []
    seen_locations: set[tuple[Path, str]] = set()

    for term in terms:
        command = [
            rg_path,
            "--color",
            "never",
            "--no-heading",
            "--line-number",
            "--column",
            "-H",
            "--max-count",
            str(LOCAL_EXACT_RESULT_LIMIT),
            "--fixed-strings",
            term,
            str(repo_path),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode not in {0, 1}:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"rg exited {completed.returncode}"
            raise RuntimeError(detail)
        if completed.returncode == 1:
            continue

        for raw_line in completed.stdout.splitlines():
            parts = raw_line.split(":", 3)
            if len(parts) != 4:
                continue
            path_text, line_number, _, content = parts
            match_path = Path(path_text)
            if not match_path.is_absolute():
                match_path = (repo_path / match_path).resolve()
            key = (match_path, line_number)
            if key in seen_locations:
                continue
            seen_locations.add(key)
            try:
                relative_path = match_path.resolve().relative_to(repo_path.resolve())
            except ValueError:
                relative_path = match_path.name
            results.append(
                SearchResult(
                    title=f"{relative_path}:{line_number}",
                    url=_local_result_url(match_path, line_number),
                    content=content.strip(),
                    source="local_exact",
                )
            )
            if len(results) >= LOCAL_EXACT_RESULT_LIMIT:
                return results

    return results


async def _safe_async_call(coro, *, timeout: float | None = None) -> tuple[object | None, str | None]:
    try:
        if timeout is not None:
            return await asyncio.wait_for(coro, timeout=timeout), None
        return await coro, None
    except Exception as e:
        detail = str(e).strip()
        return None, detail or type(e).__name__


async def _cooling_provider_result(provider: str) -> tuple[None, str]:
    return None, f"{provider}: Temporarily cooling down. Try again later."


def _sanitize_http_error(error: httpx.HTTPStatusError) -> RuntimeError:
    status_code = error.response.status_code
    if status_code == 429:
        return RuntimeError("Rate limit exceeded")
    return RuntimeError(f"HTTP {status_code}")


async def _exa_code_search(query: str, repo_full: str | None) -> list[SearchResult]:
    exa_query = f"{query} repo:{repo_full}" if repo_full else query
    config = get_config()
    provider_config = config.providers.exa_mcp

    provider = ExaMcpProvider(
        api_key=provider_config.api_key,
        api_keys=provider_config.api_keys,
        timeout=60.0,
    )
    try:
        results = await provider.code_search(exa_query, tokens_num=EXA_CODE_TOKENS_NUM)
        provider.record_success()
        return results
    except httpx.HTTPStatusError as exc:
        provider.record_http_error(exc)
        raise _sanitize_http_error(exc) from exc
    except Exception as exc:
        provider.record_transport_error(exc)
        raise
    finally:
        await provider.close()


async def _deepwiki_search(query: str, repo_full: str) -> str:
    provider = DeepWikiProvider(timeout=90.0)
    try:
        answer = await provider.ask_question(query, repo_full)
        provider.record_success()
        return answer
    except httpx.HTTPStatusError as exc:
        provider.record_http_error(exc)
        raise _sanitize_http_error(exc) from exc
    except Exception as exc:
        provider.record_transport_error(exc)
        raise
    finally:
        await provider.close()


async def _grep_app_search(query: str, repo_full: str | None) -> list[SearchResult]:
    provider = GrepAppProvider(timeout=30.0)
    try:
        results = await provider.code_search(query, repo=repo_full, max_results=10)
        provider.record_success()
        return results
    except httpx.HTTPStatusError as exc:
        provider.record_http_error(exc)
        raise _sanitize_http_error(exc) from exc
    except Exception as exc:
        provider.record_transport_error(exc)
        raise
    finally:
        await provider.close()


async def _get_github_provider(timeout: float = 30.0) -> GitHubCodeSearchProvider | None:
    provider = GitHubCodeSearchProvider(timeout=timeout)
    if await provider.is_authenticated():
        return provider
    return None


async def _github_code_search(
    query: str,
    repo_full: str | None,
    *,
    provider: GitHubCodeSearchProvider | None = None,
) -> list[SearchResult]:
    github_provider = provider or GitHubCodeSearchProvider(timeout=30.0)
    try:
        results = await github_provider.code_search(query, repo=repo_full, max_results=10)
        github_provider.record_success()
        return results
    except httpx.HTTPStatusError as exc:
        github_provider.record_http_error(exc)
        raise _sanitize_http_error(exc) from exc
    except Exception as exc:
        github_provider.record_transport_error(exc)
        raise
    finally:
        await github_provider.close()


async def _morph_search(
    query: str,
    repo_path: Path,
    api_key: str,
    base_url: str,
) -> list[SearchResult]:
    provider = MorphWarpGrepProvider(
        api_key=api_key,
        base_url=base_url,
        timeout=MORPH_TIMEOUT_SECONDS,
    )
    try:
        results = await provider.code_search(query, repo_path)
        provider.record_success()
        return results
    except httpx.HTTPStatusError as exc:
        provider.record_http_error(exc)
        raise _sanitize_http_error(exc) from exc
    except Exception as exc:
        provider.record_transport_error(exc)
        raise
    finally:
        await provider.close()


def _noodl_search(query: str, repo_path: Path) -> list[SearchResult]:
    provider = NoodlProvider()
    if not provider.is_available():
        return []
    return provider.code_search(query, repo_path, max_results=10)


async def search_code(query: str, repo: str | None = None, format: str = "markdown") -> str:
    """Search code across multiple providers in parallel."""
    config = get_config()
    health_registry = get_health_registry()
    fmt = (format or "markdown").strip().lower()
    tool_run = start_tool_call(
        "search_code",
        {
            "query": query,
            "repo": repo,
            "format": fmt,
        },
    )

    def finalize(output: str, **metadata: object) -> str:
        finish_tool_call(tool_run, result=output, metadata=metadata)
        return output

    try:
        repo_full = None
        repo_path = None
        remote_scope_enabled = repo is None
        if repo:
            try:
                repo_full, repo_path = await asyncio.to_thread(_resolve_repo, repo)
            except Exception as exc:
                detail = str(exc).strip() or type(exc).__name__
                repo_metadata = _code_repo_metadata(repo, None, None)
                if fmt == "json":
                    return finalize(
                        _render_code_search_json(
                            query=query,
                            repo=repo_metadata,
                            sections=[],
                            errors=[],
                            error=detail,
                        ),
                        repo_input=repo,
                        repo_resolution="failed",
                        response_format=fmt,
                    )
                return finalize(
                    f"**Error:** {detail}",
                    repo_input=repo,
                    repo_resolution="failed",
                    response_format=fmt,
                )
            log_event(
                "repo_context",
                repo_input=repo,
                repo_full=repo_full,
                repo_path=repo_path,
            )
            remote_scope_enabled = repo_full is not None

        # Build tasks to run in parallel
        tasks: dict[str, asyncio.Task] = {}
        provider_errors: dict[str, str | None] = {}

        if repo_path:
            local_request = {
                "query": query,
                "repo_path": repo_path,
                "terms": _extract_local_query_terms(query),
            }
            log_event(
                "provider_attempt",
                provider="local_exact",
                query=query,
                repo=repo_full,
                request=local_request,
            )
            tasks["local_exact"] = asyncio.create_task(
                _safe_async_call(
                    asyncio.to_thread(_local_exact_search, query, repo_path),
                    timeout=LOCAL_EXACT_TIMEOUT_SECONDS,
                )
            )

        if remote_scope_enabled:
            exa_request = {
                "query": f"{query} repo:{repo_full}" if repo_full else query,
                "repo": repo_full,
                "tokens_num": EXA_CODE_TOKENS_NUM,
            }
            log_event(
                "provider_attempt",
                provider="exa_mcp",
                query=query,
                repo=repo_full,
                request=exa_request,
            )
            if health_registry.is_provider_cooling("exa_mcp"):
                tasks["exa"] = asyncio.create_task(_cooling_provider_result("exa_mcp"))
            else:
                tasks["exa"] = asyncio.create_task(
                    _safe_async_call(_exa_code_search(query, repo_full), timeout=60.0)
                )

            grep_request = {
                "query": query,
                "repo": repo_full,
                "max_results": 10,
            }
            log_event(
                "provider_attempt",
                provider="grep_app",
                query=query,
                repo=repo_full,
                request=grep_request,
            )
            if health_registry.is_provider_cooling("grep_app"):
                tasks["grep"] = asyncio.create_task(_cooling_provider_result("grep_app"))
            else:
                tasks["grep"] = asyncio.create_task(
                    _safe_async_call(_grep_app_search(query, repo_full), timeout=30.0)
                )

            github_provider = await _get_github_provider(timeout=30.0)
            if github_provider is not None:
                github_request = {
                    "query": query,
                    "repo": repo_full,
                    "max_results": 10,
                }
                log_event(
                    "provider_attempt",
                    provider="github_code_search",
                    query=query,
                    repo=repo_full,
                    request=github_request,
                )
                if health_registry.is_provider_cooling("github_code_search"):
                    tasks["github"] = asyncio.create_task(
                        _cooling_provider_result("github_code_search")
                    )
                else:
                    tasks["github"] = asyncio.create_task(
                        _safe_async_call(
                            _github_code_search(query, repo_full, provider=github_provider),
                            timeout=30.0,
                        )
                    )

        # DeepWiki only if we have a repo
        if repo_full:
            deepwiki_request = {
                "query": query,
                "repo": repo_full,
            }
            log_event(
                "provider_attempt",
                provider="deepwiki",
                query=query,
                repo=repo_full,
                request=deepwiki_request,
            )
            if health_registry.is_provider_cooling("deepwiki"):
                tasks["deepwiki"] = asyncio.create_task(_cooling_provider_result("deepwiki"))
            else:
                tasks["deepwiki"] = asyncio.create_task(
                    _safe_async_call(_deepwiki_search(query, repo_full), timeout=DEEPWIKI_TIMEOUT_SECONDS)
                )

        # Morph only if we have a local repo path and API key
        if repo_path and config.settings.morph_api_key:
            morph_request = {
                "query": query,
                "repo": repo_full,
                "repo_path": repo_path,
                "base_url": config.settings.morph_base_url,
            }
            log_event(
                "provider_attempt",
                provider="morph",
                query=query,
                repo=repo_full,
                request=morph_request,
            )
            if health_registry.is_provider_cooling("morph_warp_grep"):
                tasks["morph"] = asyncio.create_task(
                    _cooling_provider_result("morph_warp_grep")
                )
            else:
                tasks["morph"] = asyncio.create_task(
                    _safe_async_call(
                        _morph_search(
                            query,
                            repo_path,
                            api_key=config.settings.morph_api_key,
                            base_url=config.settings.morph_base_url,
                        ),
                        timeout=MORPH_TIMEOUT_SECONDS,
                    )
                )

        # Noodl is temporarily disabled even when a local repo is available.
        if repo_path and NOODL_SEARCH_ENABLED:
            noodl_request = {
                "query": query,
                "repo": repo_full,
                "repo_path": repo_path,
                "max_results": 10,
            }
            log_event(
                "provider_attempt",
                provider="noodl",
                query=query,
                repo=repo_full,
                request=noodl_request,
            )
            tasks["noodl"] = asyncio.create_task(
                _safe_async_call(asyncio.to_thread(_noodl_search, query, repo_path), timeout=45.0)
            )

        # Wait for all tasks to complete
        await asyncio.gather(*tasks.values(), return_exceptions=True)

        sections: list[str] = []
        json_sections: list[dict[str, object]] = []
        json_errors: list[dict[str, str]] = []

        if "local_exact" in tasks:
            local_results_raw, local_error = tasks["local_exact"].result()
            local_results = dedupe_results(
                local_results_raw if isinstance(local_results_raw, list) else [],
                max_results=LOCAL_EXACT_RESULT_LIMIT,
            )
            effective_local_error = _clean_provider_error("local_exact", local_error)
            provider_errors["Local Exact Matches"] = effective_local_error
            _append_code_error(json_errors, "local_exact", effective_local_error)
            log_event(
                "provider_result",
                provider="local_exact",
                request=local_request,
                results=local_results,
                raw_results=local_results_raw if isinstance(local_results_raw, list) else [],
                result_count=len(local_results),
                error=effective_local_error,
                repo=repo_full,
            )
            local_section = format_results_section("Local Exact Matches", local_results)
            if local_section:
                sections.append(local_section)
            local_json_section = _build_code_matches_section("local_exact", local_results)
            if local_json_section:
                json_sections.append(local_json_section)

        # Process Exa results
        if "exa" in tasks:
            exa_results_raw, exa_error = tasks["exa"].result()
            exa_results_unfiltered = exa_results_raw if isinstance(exa_results_raw, list) else []
            exa_results = dedupe_results(_filter_repo_results(exa_results_unfiltered, repo_full))
            effective_exa_error = _clean_provider_error("exa_mcp", exa_error)
            provider_errors["Exa Code Context"] = effective_exa_error
            _append_code_error(json_errors, "exa", effective_exa_error)
            log_event(
                "provider_result",
                provider="exa_mcp",
                request=exa_request,
                results=exa_results,
                raw_results=exa_results_unfiltered,
                result_count=len(exa_results),
                raw_result_count=len(exa_results_unfiltered),
                error=effective_exa_error,
                repo=repo_full,
            )
            exa_section = format_results_section("Exa Code Context", exa_results)
            if exa_section:
                sections.append(exa_section)
            exa_json_section = _build_code_matches_section("exa", exa_results)
            if exa_json_section:
                json_sections.append(exa_json_section)

        # Process DeepWiki results
        if "deepwiki" in tasks:
            deepwiki_raw, deepwiki_error = tasks["deepwiki"].result()
            deepwiki_answer_raw = deepwiki_raw if isinstance(deepwiki_raw, str) else ""
            deepwiki_answer, deepwiki_answer_error = clean_deepwiki_answer(deepwiki_answer_raw)
            effective_deepwiki_error = _clean_provider_error(
                "deepwiki",
                deepwiki_answer_error or deepwiki_error,
            )
            provider_errors["DeepWiki"] = effective_deepwiki_error
            _append_code_error(json_errors, "deepwiki", effective_deepwiki_error)
            log_event(
                "provider_result",
                provider="deepwiki",
                request=deepwiki_request,
                answer=deepwiki_answer or deepwiki_answer_raw,
                raw_answer=deepwiki_answer_raw,
                cleaned_answer=deepwiki_answer,
                result_count=1 if deepwiki_answer else 0,
                error=effective_deepwiki_error,
                repo=repo_full,
            )
            if deepwiki_answer:
                sections.append(f"## DeepWiki\n{deepwiki_answer}")
            deepwiki_json_section = _build_code_answer_section("deepwiki", deepwiki_answer)
            if deepwiki_json_section:
                json_sections.append(deepwiki_json_section)

        # Process GitHub Code Search results
        if "github" in tasks:
            github_results_raw, github_error = tasks["github"].result()
            github_results_unfiltered = (
                github_results_raw if isinstance(github_results_raw, list) else []
            )
            github_results = dedupe_results(_filter_repo_results(github_results_unfiltered, repo_full))
            effective_github_error = _clean_provider_error("github_code_search", github_error)
            provider_errors["GitHub Code Search"] = effective_github_error
            _append_code_error(json_errors, "github", effective_github_error)
            log_event(
                "provider_result",
                provider="github_code_search",
                request=github_request,
                results=github_results,
                raw_results=github_results_unfiltered,
                result_count=len(github_results),
                raw_result_count=len(github_results_unfiltered),
                error=effective_github_error,
                repo=repo_full,
            )
            github_section = format_results_section("GitHub Code Search", github_results)
            if github_section:
                sections.append(github_section)
            github_json_section = _build_code_matches_section("github", github_results)
            if github_json_section:
                json_sections.append(github_json_section)

        # Process grep.app results
        if "grep" in tasks:
            grep_results_raw, grep_error = tasks["grep"].result()
            grep_results_unfiltered = grep_results_raw if isinstance(grep_results_raw, list) else []
            grep_results = dedupe_results(_filter_repo_results(grep_results_unfiltered, repo_full))
            effective_grep_error = _clean_provider_error("grep_app", grep_error)
            provider_errors["grep.app"] = effective_grep_error
            _append_code_error(json_errors, "grep", effective_grep_error)
            log_event(
                "provider_result",
                provider="grep_app",
                request=grep_request,
                results=grep_results,
                raw_results=grep_results_unfiltered,
                result_count=len(grep_results),
                raw_result_count=len(grep_results_unfiltered),
                error=effective_grep_error,
                repo=repo_full,
            )
            grep_section = format_results_section("grep.app", grep_results)
            if grep_section:
                sections.append(grep_section)
            grep_json_section = _build_code_matches_section("grep", grep_results)
            if grep_json_section:
                json_sections.append(grep_json_section)

        # Process Morph results
        if "morph" in tasks:
            morph_results_raw, morph_error = tasks["morph"].result()
            morph_results = dedupe_results(
                morph_results_raw if isinstance(morph_results_raw, list) else []
            )
            effective_morph_error = _clean_provider_error("morph", morph_error)
            provider_errors["Morph Warp Grep"] = effective_morph_error
            _append_code_error(json_errors, "morph", effective_morph_error)
            log_event(
                "provider_result",
                provider="morph",
                request=morph_request,
                results=morph_results,
                raw_results=morph_results_raw if isinstance(morph_results_raw, list) else [],
                result_count=len(morph_results),
                error=effective_morph_error,
                repo=repo_full,
            )
            morph_section = format_results_section("Morph Warp Grep", morph_results)
            if morph_section:
                sections.append(morph_section)
            morph_json_section = _build_code_matches_section("morph", morph_results)
            if morph_json_section:
                json_sections.append(morph_json_section)

        # Process Noodl results
        if "noodl" in tasks:
            noodl_results_raw, noodl_error = tasks["noodl"].result()
            noodl_results = dedupe_results(
                noodl_results_raw if isinstance(noodl_results_raw, list) else []
            )
            effective_noodl_error = _clean_provider_error("noodl", noodl_error)
            provider_errors["Noodl"] = effective_noodl_error
            _append_code_error(json_errors, "noodl", effective_noodl_error)

            log_event(
                "provider_result",
                provider="noodl",
                request=noodl_request,
                results=noodl_results,
                raw_results=noodl_results_raw if isinstance(noodl_results_raw, list) else [],
                result_count=len(noodl_results),
                error=effective_noodl_error,
                repo=repo_full,
            )
            noodl_section = format_results_section("Noodl", noodl_results)
            if noodl_section:
                sections.append(noodl_section)
            noodl_json_section = _build_code_matches_section("noodl", noodl_results)
            if noodl_json_section:
                json_sections.append(noodl_json_section)

        repo_metadata = _code_repo_metadata(repo, repo_full, repo_path)
        if fmt == "json":
            return finalize(
                _render_code_search_json(
                    query=query,
                    repo=repo_metadata,
                    sections=json_sections,
                    errors=json_errors,
                ),
                repo_full=repo_full,
                repo_path=repo_path,
                response_format=fmt,
                section_count=len(json_sections),
                error_count=len(json_errors),
            )

        if not sections:
            error_sections = [
                format_error_section(title, error)
                for title, error in provider_errors.items()
                if error
            ]
            if error_sections:
                return finalize(
                    "\n\n".join(section for section in error_sections if section),
                    repo_full=repo_full,
                    repo_path=repo_path,
                    response_format=fmt,
                )
            return finalize(
                "No results found.",
                repo_full=repo_full,
                repo_path=repo_path,
                response_format=fmt,
            )

        return finalize(
            "\n\n".join(sections).strip(),
            repo_full=repo_full,
            repo_path=repo_path,
            response_format=fmt,
        )
    except Exception as error:
        fail_tool_call(tool_run, error=error, metadata={"repo": repo})
        raise
