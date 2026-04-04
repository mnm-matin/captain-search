"""Reusable helpers for Captain Search tests."""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from captain_search.providers.base import FetchResponse, SearchResult

PROVIDER_ENV_VARS = (
    "SERPER_API_KEY",
    "SERPER_API_KEYS",
    "BRAVE_API_KEY",
    "BRAVE_API_KEYS",
    "TAVILY_API_KEY",
    "TAVILY_API_KEYS",
    "PERPLEXITY_API_KEY",
    "PERPLEXITY_API_KEYS",
    "PARALLEL_API_KEY",
    "PARALLEL_API_KEYS",
    "JINA_API_KEY",
    "JINA_API_KEYS",
    "EXA_API_KEY",
    "EXA_API_KEYS",
)

DEFAULT_MORPH_BASE_URL = "https://api.morphllm.com"
WEB_PROVIDER_NAMES = (
    "serper",
    "brave",
    "tavily",
    "perplexity",
    "parallel",
    "exa",
    "exa_mcp",
)
FETCH_PROVIDER_NAMES = ("parallel", "jina", "exa", "tavily")
CODE_PROVIDER_NAMES = (
    "exa_mcp",
    "grep_app",
    "deepwiki",
    "github_code_search",
    "morph",
)

_FETCH_METHOD_TARGETS = {
    "parallel": "captain_search.tools.fetch.ParallelProvider.fetch",
    "jina": "captain_search.tools.fetch.JinaProvider.fetch",
    "exa": "captain_search.tools.fetch.ExaProvider.fetch",
    "tavily": "captain_search.tools.fetch.TavilyProvider.fetch",
}
_UNSET = object()


def clear_provider_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in PROVIDER_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)


def skip_if_no_e2e() -> None:
    if not os.getenv("RUN_E2E"):
        pytest.skip("Set RUN_E2E=1 to run networked smoke tests")


def provider_settings(
    *,
    enabled: bool = False,
    api_key: str | None = None,
    api_keys: list[str] | None = None,
    weight: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=enabled,
        api_key=api_key,
        api_keys=list(api_keys or []),
        weight=weight,
    )


def make_config(
    *,
    providers: dict[str, object] | None = None,
    settings: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        providers=SimpleNamespace(**(providers or {})),
        settings=settings
        or SimpleNamespace(morph_api_key=None, morph_base_url=DEFAULT_MORPH_BASE_URL),
    )


def search_result(
    *,
    title: str,
    url: str,
    content: str,
    source: str,
) -> SearchResult:
    return SearchResult(title=title, url=url, content=content, source=source)


def fetch_response(
    *,
    url: str,
    title: str,
    content: str,
    format: str = "markdown",
    status: int | None = None,
    error: str | None = None,
) -> FetchResponse:
    return FetchResponse(
        url=url,
        title=title,
        content=content,
        format=format,
        status=status,
        error=error,
    )


class StaticSearchProvider:
    def __init__(
        self,
        *,
        results: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self._results = results or []
        self._error = error

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        if self._error is not None:
            raise self._error

        if callable(self._results):
            results = self._results(query, max_results)
            if inspect.isawaitable(results):
                results = await results
            return list(results)

        return list(self._results)

    async def close(self) -> None:
        return None


def patch_search_provider_factory(
    monkeypatch: pytest.MonkeyPatch,
    *,
    providers: dict[str, object],
    config: object | None = None,
    selected: str | None = None,
) -> None:
    if config is not None:
        monkeypatch.setattr("captain_search.tools.search.get_config", lambda: config)
    if selected is not None:
        monkeypatch.setattr(
            "captain_search.tools.search._weighted_random_choice",
            lambda weights: selected,
        )
    monkeypatch.setattr(
        "captain_search.tools.search._get_provider_instance",
        lambda name, config: providers.get(name),
    )


def _wrap_async(handler: object):
    async def wrapped(*args, **kwargs):
        if callable(handler):
            result = handler(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
        else:
            result = handler
        if isinstance(result, Exception):
            raise result
        return result

    return wrapped


def _wrap_sync(handler: object):
    def wrapped(*args, **kwargs):
        result = handler(*args, **kwargs) if callable(handler) else handler
        if isinstance(result, Exception):
            raise result
        return result

    return wrapped


def patch_fetch_providers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: object,
    providers: dict[str, object],
    selected: str | None = None,
    fallback: object = _UNSET,
) -> None:
    monkeypatch.setattr("captain_search.tools.fetch.get_config", lambda: config)
    if selected is not None:
        monkeypatch.setattr(
            "captain_search.tools.fetch._weighted_random_choice",
            lambda weights: selected,
        )
    for provider_name, handler in providers.items():
        monkeypatch.setattr(_FETCH_METHOD_TARGETS[provider_name], _wrap_async(handler))
    if fallback is not _UNSET:
        monkeypatch.setattr(
            "captain_search.tools.fetch._fetch_with_local_fallback",
            _wrap_async(fallback),
        )


def patch_code_search_backends(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: object | None = None,
    health_registry: object | None = None,
    resolve_repo: object = _UNSET,
    repo_full: str | None = None,
    repo_path: Path | None = None,
    exa: object = (),
    grep: object = (),
    deepwiki: object = "",
    github: object = None,
    github_search: object = _UNSET,
    local: object = _UNSET,
    noodl: object = (),
) -> None:
    monkeypatch.setattr(
        "captain_search.tools.code_search.get_config",
        lambda: config or make_config(),
    )
    if health_registry is not None:
        monkeypatch.setattr(
            "captain_search.tools.code_search.get_health_registry",
            lambda: health_registry,
        )
    if resolve_repo is not _UNSET:
        monkeypatch.setattr("captain_search.tools.code_search._resolve_repo", resolve_repo)
    elif repo_full is not None or repo_path is not None:
        monkeypatch.setattr(
            "captain_search.tools.code_search._resolve_repo",
            lambda repo: (repo_full, repo_path),
        )
    monkeypatch.setattr("captain_search.tools.code_search._exa_code_search", _wrap_async(exa))
    monkeypatch.setattr("captain_search.tools.code_search._grep_app_search", _wrap_async(grep))
    monkeypatch.setattr("captain_search.tools.code_search._deepwiki_search", _wrap_async(deepwiki))
    monkeypatch.setattr("captain_search.tools.code_search._get_github_provider", _wrap_async(github))
    if github_search is not _UNSET:
        monkeypatch.setattr(
            "captain_search.tools.code_search._github_code_search",
            _wrap_async(github_search),
        )
    monkeypatch.setattr("captain_search.tools.code_search._noodl_search", _wrap_sync(noodl))
    if local is not _UNSET:
        monkeypatch.setattr("captain_search.tools.code_search._local_exact_search", _wrap_sync(local))