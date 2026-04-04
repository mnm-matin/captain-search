"""Behavior tests for search_web."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from captain_search.tools import search_web
from tests._helpers import (
    WEB_PROVIDER_NAMES,
    StaticSearchProvider,
    patch_search_provider_factory,
    search_result,
)


def _unauthorized_http_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.perplexity.ai/search")
    response = httpx.Response(401, request=request)
    return httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)


def test_site_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    class WeightedConfig:
        providers = object()

        def get_provider_weights(self) -> dict[str, int]:
            return {"serper": 1, "brave": 1}

    patch_search_provider_factory(
        monkeypatch,
        config=WeightedConfig(),
        selected="serper",
        providers={
            "serper": StaticSearchProvider(
                results=[
                    search_result(
                        title="cloudrive",
                        url="https://www.npmjs.com/package/cloudrive",
                        content="Install cloudrive from npm.",
                        source="serper",
                    )
                ]
            ),
            "brave": StaticSearchProvider(
                results=[
                    search_result(
                        title="clawdrive",
                        url="https://www.npmjs.com/package/clawdrive",
                        content="clawdrive package on npm",
                        source="brave",
                    )
                ]
            ),
        },
    )

    output = asyncio.run(
        search_web(
            query="site:npmjs.com/package clawdrive",
            max_results=3,
            format="json",
        )
    )

    payload = json.loads(output)
    assert [result["title"] for result in payload["results"]] == ["clawdrive"]


@pytest.mark.parametrize("provider_name", WEB_PROVIDER_NAMES, ids=WEB_PROVIDER_NAMES)
def test_explicit_provider(monkeypatch: pytest.MonkeyPatch, provider_name: str) -> None:
    patch_search_provider_factory(
        monkeypatch,
        config=object(),
        providers={
            provider_name: StaticSearchProvider(
                results=[
                    search_result(
                        title=f"{provider_name} result",
                        url=f"https://example.com/{provider_name}",
                        content="provider result",
                        source=provider_name,
                    )
                ]
            )
        },
    )

    output = asyncio.run(
        search_web(
            query="captain search provider contract",
            max_results=2,
            format="json",
            provider=provider_name,
        )
    )

    payload = json.loads(output)
    assert payload["results"][0]["title"] == f"{provider_name} result"


def test_invalid_max_results() -> None:
    output = asyncio.run(search_web(query="parallel ai search", max_results=0, format="json"))

    payload = json.loads(output)
    assert payload["results"] == []
    assert payload["error"] == "max_results must be between 1 and 50."


def test_unknown_provider_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_search_provider_factory(
        monkeypatch,
        config=object(),
        providers={
            "parallel": StaticSearchProvider(
                results=[
                    search_result(
                        title="Parallel result",
                        url="https://parallel.ai/search",
                        content="search result",
                        source="parallel",
                    )
                ]
            )
        },
    )

    json_output = asyncio.run(
        search_web(
            query="parallel ai search",
            max_results=2,
            format="json",
            provider="parallel,not_a_provider",
        )
    )
    markdown_output = asyncio.run(
        search_web(
            query="parallel ai search",
            max_results=2,
            format="markdown",
            provider="parallel,not_a_provider",
        )
    )

    payload = json.loads(json_output)
    assert payload["warnings"] == ["Ignored unknown provider(s): not_a_provider"]
    assert payload["results"][0]["title"] == "Parallel result"
    assert markdown_output.startswith("**Warning:** Ignored unknown provider(s): not_a_provider")


def test_multi_provider_result_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_search_provider_factory(
        monkeypatch,
        config=object(),
        providers={
            name: StaticSearchProvider(
                results=lambda query, max_results, name=name: [
                    search_result(
                        title=f"{name}-{index}",
                        url=f"https://example.com/{name}/{index}",
                        content=query,
                        source=name,
                    )
                    for index in range(max_results)
                ]
            )
            for name in ("serper", "brave")
        },
    )

    output = asyncio.run(
        search_web(
            query="captain search alternatives",
            max_results=3,
            format="json",
            provider="serper,brave",
        )
    )

    payload = json.loads(output)
    assert len(payload["results"]) == 3


def test_public_markdown_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class WeightedConfig:
        def get_provider_weights(self) -> dict[str, int]:
            return {"perplexity": 1}

    patch_search_provider_factory(
        monkeypatch,
        config=WeightedConfig(),
        providers={"perplexity": StaticSearchProvider(error=_unauthorized_http_error())},
    )

    output = asyncio.run(search_web(query="captain search", max_results=1, format="markdown"))

    assert output == (
        "**Error:** Search failed across configured providers. "
        "Check Captain Search logs for provider-specific errors."
    )
    assert "PERPLEXITY_API_KEY" not in output


def test_public_json_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_search_provider_factory(
        monkeypatch,
        config=object(),
        providers={"perplexity": StaticSearchProvider(error=_unauthorized_http_error())},
    )

    output = asyncio.run(
        search_web(
            query="captain search",
            max_results=1,
            format="json",
            provider="perplexity",
        )
    )

    payload = json.loads(output)
    assert payload["error"] == (
        "Search failed for the requested providers. "
        "Check Captain Search logs for provider-specific errors."
    )
    assert "PERPLEXITY_API_KEY" not in payload["error"]