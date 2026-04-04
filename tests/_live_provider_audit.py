"""Shared helpers for live provider audits and session summaries."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from captain_search.config import Config, get_config
from captain_search.providers.brave import BraveProvider
from captain_search.providers.deepwiki import DeepWikiProvider
from captain_search.providers.exa import ExaProvider
from captain_search.providers.exa_mcp import ExaMcpProvider
from captain_search.providers.github_code_search import (
    GitHubCodeSearchProvider,
    get_gh_cli_auth_state,
)
from captain_search.providers.grep_app import GrepAppProvider
from captain_search.providers.jina import JinaProvider
from captain_search.providers.morph import MorphWarpGrepProvider
from captain_search.providers.parallel import ParallelProvider
from captain_search.providers.perplexity import PerplexityProvider
from captain_search.providers.serper import SerperProvider
from captain_search.providers.tavily import TavilyProvider
from tests._helpers import CODE_PROVIDER_NAMES, FETCH_PROVIDER_NAMES, WEB_PROVIDER_NAMES

LIVE_PROVIDER_AUDIT_CACHE_KEY = "captain_search/live_provider_audit"
DEFAULT_CACHE_TTL_SECONDS = 1800

WEB_PROVIDERS = WEB_PROVIDER_NAMES
CODE_PROVIDERS = CODE_PROVIDER_NAMES
FETCH_PROVIDERS = FETCH_PROVIDER_NAMES

WEB_QUERY = "openai api"
WEB_MAX_RESULTS = 1
CODE_QUERY = "contextmanager"
CODE_REPO = "python/cpython"
DEEPWIKI_QUESTION = "Where is contextmanager implemented?"
LOCAL_CODE_QUERY = "search_web"
FETCH_URL = "https://example.com"

TASK_LABELS = {
    "web_search": "Web Search",
    "code_search": "Code Search",
    "fetch": "Fetch",
}


def _cache_ttl_seconds() -> int:
    raw_value = os.getenv("LIVE_PROVIDER_CACHE_TTL_SECONDS", str(DEFAULT_CACHE_TTL_SECONDS)).strip()
    try:
        return max(0, int(raw_value))
    except ValueError:
        return DEFAULT_CACHE_TTL_SECONDS


def _force_refresh() -> bool:
    return os.getenv("LIVE_PROVIDER_FORCE_REFRESH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _has_keys(provider_config: object | None) -> bool:
    if provider_config is None:
        return False
    api_key = getattr(provider_config, "api_key", None)
    api_keys = getattr(provider_config, "api_keys", None) or []
    return bool(api_key or api_keys)


def _provider_kind(provider: str) -> str:
    if provider in {"grep_app", "deepwiki", "github_code_search"}:
        return "builtin"
    return "configured"


def _not_configured_details(task: str, provider: str) -> str:
    if task == "code_search" and provider == "github_code_search":
        gh_installed, gh_authenticated = get_gh_cli_auth_state()
        if not gh_installed:
            return "gh CLI not installed"
        if not gh_authenticated:
            return "gh CLI not authenticated"
    if task == "code_search" and provider == "morph":
        return "MORPH_API_KEY not set"
    if task == "web_search" and provider == "exa_mcp":
        return "Provider disabled"
    if task == "fetch" and provider == "jina":
        return "Provider disabled"
    return "Disabled or missing credentials"


def _workspace_repo_path() -> Path:
    return Path(__file__).resolve().parents[1]


def _web_provider_active(config: Config, provider: str) -> bool:
    if provider == "exa_mcp":
        return bool(config.providers.exa_mcp.enabled)
    provider_config = getattr(config.providers, provider, None)
    return bool(provider_config and provider_config.enabled and _has_keys(provider_config))


def _code_provider_active(config: Config, provider: str) -> bool:
    if provider == "exa_mcp":
        return bool(config.providers.exa_mcp.enabled)
    if provider in {"grep_app", "deepwiki"}:
        return True
    if provider == "github_code_search":
        gh_installed, gh_authenticated = get_gh_cli_auth_state()
        return gh_installed and gh_authenticated
    if provider == "morph":
        return bool(config.settings.morph_api_key)
    return False


def _fetch_provider_active(config: Config, provider: str) -> bool:
    provider_config = getattr(config.providers, provider, None)
    if provider == "jina":
        return bool(provider_config and provider_config.enabled)
    return bool(provider_config and provider_config.enabled and _has_keys(provider_config))


def _row(provider: str, *, task: str, active: bool, status: str, details: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "task": task,
        "kind": _provider_kind(provider),
        "active": active,
        "status": status,
        "details": " ".join(details.split()),
    }


def _ok_row(provider: str, *, task: str, details: str) -> dict[str, Any]:
    return _row(provider, task=task, active=True, status="ok", details=details)


def _failed_row(provider: str, *, task: str, details: str) -> dict[str, Any]:
    return _row(provider, task=task, active=True, status="failed", details=details)


def _inactive_row(provider: str, *, task: str) -> dict[str, Any]:
    return _row(
        provider,
        task=task,
        active=False,
        status="not_configured",
        details=_not_configured_details(task, provider),
    )


def _error_details(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        if status_code == 401:
            return "HTTP 401 unauthorized"
        if status_code == 403:
            return "HTTP 403 forbidden"
        if status_code == 429:
            return "HTTP 429 rate limited"
        return f"HTTP {status_code}"
    detail = str(error).strip()
    return detail or type(error).__name__


async def _audit_web_provider(config: Config, provider: str) -> dict[str, Any]:
    if not _web_provider_active(config, provider):
        return _inactive_row(provider, task="web_search")

    if provider == "serper":
        provider_instance = SerperProvider(
            api_key=config.providers.serper.api_key,
            api_keys=config.providers.serper.api_keys,
            timeout=30.0,
        )
    elif provider == "brave":
        provider_instance = BraveProvider(
            api_key=config.providers.brave.api_key,
            api_keys=config.providers.brave.api_keys,
            timeout=30.0,
        )
    elif provider == "tavily":
        provider_instance = TavilyProvider(
            api_key=config.providers.tavily.api_key,
            api_keys=config.providers.tavily.api_keys,
            timeout=30.0,
        )
    elif provider == "perplexity":
        provider_instance = PerplexityProvider(
            api_key=config.providers.perplexity.api_key,
            api_keys=config.providers.perplexity.api_keys,
            timeout=30.0,
        )
    elif provider == "parallel":
        provider_instance = ParallelProvider(
            api_key=config.providers.parallel.api_key,
            api_keys=config.providers.parallel.api_keys,
            timeout=30.0,
        )
    elif provider == "exa":
        provider_instance = ExaProvider(
            api_key=config.providers.exa.api_key,
            api_keys=config.providers.exa.api_keys,
            timeout=30.0,
        )
    elif provider == "exa_mcp":
        provider_instance = ExaMcpProvider(
            api_key=config.providers.exa_mcp.api_key,
            api_keys=config.providers.exa_mcp.api_keys,
            timeout=30.0,
        )
    else:
        return _failed_row(provider, task="web_search", details="Unknown provider")

    try:
        results = await provider_instance.search(WEB_QUERY, max_results=WEB_MAX_RESULTS)
        if not results:
            return _failed_row(provider, task="web_search", details="No results returned")
        return _ok_row(provider, task="web_search", details=f"{len(results)} result(s)")
    except Exception as error:
        return _failed_row(provider, task="web_search", details=_error_details(error))
    finally:
        await provider_instance.close()


async def _audit_code_provider(config: Config, provider: str) -> dict[str, Any]:
    if not _code_provider_active(config, provider):
        return _inactive_row(provider, task="code_search")

    if provider == "exa_mcp":
        provider_instance = ExaMcpProvider(
            api_key=config.providers.exa_mcp.api_key,
            api_keys=config.providers.exa_mcp.api_keys,
            timeout=60.0,
        )
        try:
            results = await provider_instance.code_search(
                f"{CODE_QUERY} repo:{CODE_REPO}",
                tokens_num=5000,
            )
            if not results:
                return _failed_row(provider, task="code_search", details="No results returned")
            return _ok_row(provider, task="code_search", details=f"{len(results)} result(s)")
        except Exception as error:
            return _failed_row(provider, task="code_search", details=_error_details(error))
        finally:
            await provider_instance.close()

    if provider == "grep_app":
        provider_instance = GrepAppProvider(timeout=30.0)
        try:
            results = await provider_instance.code_search(CODE_QUERY, repo=CODE_REPO, max_results=5)
            if not results:
                return _failed_row(provider, task="code_search", details="No results returned")
            return _ok_row(provider, task="code_search", details=f"{len(results)} result(s)")
        except Exception as error:
            return _failed_row(provider, task="code_search", details=_error_details(error))
        finally:
            await provider_instance.close()

    if provider == "deepwiki":
        provider_instance = DeepWikiProvider(timeout=60.0)
        try:
            answer = await provider_instance.ask_question(DEEPWIKI_QUESTION, CODE_REPO)
            if not answer.strip():
                return _failed_row(provider, task="code_search", details="No answer returned")
            if "Repository not found" in answer:
                return _failed_row(provider, task="code_search", details="Repository not indexed")
            return _ok_row(provider, task="code_search", details="Answer returned")
        except Exception as error:
            return _failed_row(provider, task="code_search", details=_error_details(error))
        finally:
            await provider_instance.close()

    if provider == "github_code_search":
        provider_instance = GitHubCodeSearchProvider(timeout=30.0)
        try:
            results = await provider_instance.code_search(CODE_QUERY, repo=CODE_REPO, max_results=5)
            if not results:
                return _failed_row(provider, task="code_search", details="No results returned")
            return _ok_row(provider, task="code_search", details=f"{len(results)} result(s)")
        except Exception as error:
            return _failed_row(provider, task="code_search", details=_error_details(error))
        finally:
            await provider_instance.close()

    if provider == "morph":
        provider_instance = MorphWarpGrepProvider(
            api_key=config.settings.morph_api_key,
            base_url=config.settings.morph_base_url,
            timeout=120.0,
        )
        try:
            results = await provider_instance.code_search(LOCAL_CODE_QUERY, _workspace_repo_path())
            if not results:
                return _failed_row(provider, task="code_search", details="No results returned")
            return _ok_row(provider, task="code_search", details=f"{len(results)} result(s)")
        except Exception as error:
            return _failed_row(provider, task="code_search", details=_error_details(error))
        finally:
            await provider_instance.close()

    return _failed_row(provider, task="code_search", details="Unknown provider")


async def _audit_fetch_provider(config: Config, provider: str) -> dict[str, Any]:
    if not _fetch_provider_active(config, provider):
        return _inactive_row(provider, task="fetch")

    if provider == "parallel":
        provider_instance = ParallelProvider(
            api_key=config.providers.parallel.api_key,
            api_keys=config.providers.parallel.api_keys,
            timeout=60.0,
        )
    elif provider == "jina":
        provider_instance = JinaProvider(
            api_key=config.providers.jina.api_key,
            api_keys=config.providers.jina.api_keys,
            timeout=60.0,
        )
    elif provider == "exa":
        provider_instance = ExaProvider(
            api_key=config.providers.exa.api_key,
            api_keys=config.providers.exa.api_keys,
            timeout=60.0,
        )
    elif provider == "tavily":
        provider_instance = TavilyProvider(
            api_key=config.providers.tavily.api_key,
            api_keys=config.providers.tavily.api_keys,
            timeout=60.0,
        )
    else:
        return _failed_row(provider, task="fetch", details="Unknown provider")

    try:
        response = await provider_instance.fetch(FETCH_URL, format="markdown")
        if response.error:
            return _failed_row(provider, task="fetch", details=response.error)
        if not response.content.strip():
            return _failed_row(provider, task="fetch", details="No content returned")
        return _ok_row(provider, task="fetch", details=f"{len(response.content)} chars")
    except Exception as error:
        return _failed_row(provider, task="fetch", details=_error_details(error))
    finally:
        await provider_instance.close()


async def run_live_provider_audit() -> dict[str, Any]:
    config = get_config()
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_at_epoch": time.time(),
        "source": "live",
        "tasks": {
            "web_search": [],
            "code_search": [],
            "fetch": [],
        },
    }

    for provider in WEB_PROVIDERS:
        report["tasks"]["web_search"].append(await _audit_web_provider(config, provider))
    for provider in CODE_PROVIDERS:
        report["tasks"]["code_search"].append(await _audit_code_provider(config, provider))
    for provider in FETCH_PROVIDERS:
        report["tasks"]["fetch"].append(await _audit_fetch_provider(config, provider))

    return report


def get_session_live_provider_report(pytestconfig: Any) -> dict[str, Any] | None:
    report = getattr(pytestconfig, "_captain_search_live_provider_report", None)
    return report if isinstance(report, dict) else None


def set_session_live_provider_report(pytestconfig: Any, report: dict[str, Any]) -> None:
    pytestconfig._captain_search_live_provider_report = report


def load_cached_live_provider_report(pytestconfig: Any) -> dict[str, Any] | None:
    ttl_seconds = _cache_ttl_seconds()
    if ttl_seconds <= 0 or _force_refresh():
        return None

    cached = pytestconfig.cache.get(LIVE_PROVIDER_AUDIT_CACHE_KEY, None)
    if not isinstance(cached, dict):
        return None

    generated_at_epoch = float(cached.get("generated_at_epoch", 0.0) or 0.0)
    if generated_at_epoch <= 0:
        return None

    age_seconds = int(max(0.0, time.time() - generated_at_epoch))
    if age_seconds > ttl_seconds:
        return None

    report = dict(cached)
    report["source"] = "cache"
    report["cache_age_seconds"] = age_seconds
    report["cache_ttl_seconds"] = ttl_seconds
    return report


def save_live_provider_report(pytestconfig: Any, report: dict[str, Any]) -> None:
    to_cache = dict(report)
    to_cache["source"] = "live"
    to_cache.pop("cache_age_seconds", None)
    to_cache.pop("cache_ttl_seconds", None)
    pytestconfig.cache.set(LIVE_PROVIDER_AUDIT_CACHE_KEY, to_cache)


def get_or_run_live_provider_report(pytestconfig: Any) -> dict[str, Any]:
    existing = get_session_live_provider_report(pytestconfig)
    if existing is not None:
        return existing

    cached = load_cached_live_provider_report(pytestconfig)
    if cached is not None:
        set_session_live_provider_report(pytestconfig, cached)
        return cached

    report = asyncio.run(run_live_provider_audit())
    save_live_provider_report(pytestconfig, report)
    set_session_live_provider_report(pytestconfig, report)
    return report


def task_rows(report: dict[str, Any], task: str) -> list[dict[str, Any]]:
    tasks = report.get("tasks", {})
    rows = tasks.get(task, []) if isinstance(tasks, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def task_failures(
    report: dict[str, Any],
    task: str,
    *,
    include_builtin: bool = True,
) -> list[dict[str, Any]]:
    rows = task_rows(report, task)
    return [
        row
        for row in rows
        if row.get("active")
        and row.get("status") != "ok"
        and (include_builtin or row.get("kind") != "builtin")
    ]


def _count_status(rows: list[dict[str, Any]], *, kind: str | None = None) -> tuple[int, int]:
    scoped = [row for row in rows if row.get("active") and (kind is None or row.get("kind") == kind)]
    ok_count = sum(1 for row in scoped if row.get("status") == "ok")
    return ok_count, len(scoped)


def render_task_matrix(report: dict[str, Any], task: str) -> str:
    rows = task_rows(report, task)
    label = TASK_LABELS.get(task, task)
    lines = [
        f"{label}",
        "| Provider | Kind | Active | Status | Details |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {provider} | {kind} | {active} | {status} | {details} |".format(
                provider=row.get("provider", "?"),
                kind=row.get("kind", "?"),
                active="yes" if row.get("active") else "no",
                status=row.get("status", "?"),
                details=str(row.get("details", "")).replace("|", "\\|"),
            )
        )
    return "\n".join(lines)


def render_live_provider_summary(report: dict[str, Any]) -> str:
    lines = []
    source = report.get("source", "live")
    generated_at = report.get("generated_at", "unknown")
    if source == "cache":
        lines.append(
            "Source: cache ({age}s old, ttl {ttl}s, generated {generated})".format(
                age=report.get("cache_age_seconds", "?"),
                ttl=report.get("cache_ttl_seconds", "?"),
                generated=generated_at,
            )
        )
    else:
        lines.append(f"Source: live ({generated_at})")

    for task in ("web_search", "code_search", "fetch"):
        rows = task_rows(report, task)
        overall_ok, overall_active = _count_status(rows)
        configured_ok, configured_active = _count_status(rows, kind="configured")
        builtin_ok, builtin_active = _count_status(rows, kind="builtin")

        summary = (
            f"{TASK_LABELS.get(task, task)}: configured {configured_ok}/{configured_active} working, "
            f"builtin {builtin_ok}/{builtin_active} working, overall {overall_ok}/{overall_active} active"
        )
        lines.append(summary)
        lines.append(render_task_matrix(report, task))

    return "\n\n".join(lines)