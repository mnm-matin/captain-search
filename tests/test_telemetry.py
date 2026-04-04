"""Telemetry-focused tests for tool event logging."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from captain_search.config import reset_config
from captain_search.telemetry import get_log_file_path
from captain_search.tools import fetch_webpage, search_code, search_web
from tests._helpers import (
    StaticSearchProvider,
    clear_provider_envs,
    fetch_response,
    make_config,
    patch_code_search_backends,
    patch_fetch_providers,
    patch_search_provider_factory,
    provider_settings,
    search_result,
)

DEEPWIKI_ANSWER = "Captain Search exposes web, code, and fetch tools through one MCP server."


@pytest.fixture(autouse=True)
def telemetry_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clear_provider_envs(monkeypatch)
    monkeypatch.setenv("CAPTAIN_SEARCH_LOG_ENABLED", "true")
    monkeypatch.setenv("CAPTAIN_SEARCH_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("CAPTAIN_SEARCH_LOG_FULL_PAYLOADS", "true")
    monkeypatch.setenv("MORPH_API_KEY", "")
    reset_config()
    yield
    reset_config()


def _read_events() -> list[dict[str, object]]:
    log_path = get_log_file_path()
    assert log_path.exists(), f"Expected telemetry log at {log_path}"
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]


def _event(events: list[dict[str, object]], name: str, **fields: object) -> dict[str, object]:
    return next(
        event
        for event in events
        if event["event"] == name and all(event.get(key) == value for key, value in fields.items())
    )


def _last_event(events: list[dict[str, object]], name: str) -> dict[str, object]:
    return next(event for event in reversed(events) if event["event"] == name)


def _jina_only_fetch_config() -> object:
    return make_config(
        providers={
            "parallel": provider_settings(enabled=False),
            "jina": provider_settings(enabled=True),
        }
    )


def test_web_search_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_search_provider_factory(
        monkeypatch,
        providers={
            "exa_mcp": StaticSearchProvider(
                results=lambda query, max_results: [
                    search_result(
                        title="Captain Search alternative",
                        url="https://example.com/alt",
                        content=f"query={query}; max_results={max_results}",
                        source="exa_mcp",
                    )
                ]
            )
        },
    )

    output = asyncio.run(
        search_web(
            query="captain search alternatives",
            max_results=1,
            format="json",
            provider="exa_mcp",
        )
    )

    payload = json.loads(output)
    assert payload["results"][0]["title"] == "Captain Search alternative"

    events = _read_events()
    start = _event(events, "tool_start")
    provider_result = _event(events, "provider_result", provider="exa_mcp")
    finish = _event(events, "tool_finish")

    assert start["arguments"]["query"] == "captain search alternatives"
    assert provider_result["results"][0]["title"] == "Captain Search alternative"
    assert "Captain Search alternative" in finish["result"]


def test_code_search_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_path = Path("/tmp/captain-search")

    patch_code_search_backends(
        monkeypatch,
        repo_full="mnm-matin/captain-search",
        repo_path=repo_path,
        exa=lambda query, repo_full: [
            search_result(
                title="Telemetry wiring",
                url="https://github.com/mnm-matin/captain-search/blob/main/src/captain_search/telemetry.py",
                content=f"repo={repo_full}; query={query}",
                source="exa_mcp",
            )
        ],
        deepwiki=DEEPWIKI_ANSWER,
        local=[],
    )

    output = asyncio.run(search_code(query="captain search updates", repo="mnm-matin/captain-search"))

    events = _read_events()
    deepwiki_event = _event(events, "provider_result", provider="deepwiki")
    finish = _event(events, "tool_finish")

    assert deepwiki_event["answer"] == DEEPWIKI_ANSWER
    assert "Telemetry wiring" in finish["result"]
    assert "DeepWiki" in output


def test_fetch_fallback_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_fetch_providers(
        monkeypatch,
        config=_jina_only_fetch_config(),
        providers={
            "jina": fetch_response(
                url="https://example.com/captain-search",
                title="",
                content="",
                error="upstream timeout",
            )
        },
        fallback=fetch_response(
            url="https://example.com/captain-search",
            title="Captain Search",
            content="Updated documentation body",
        ),
    )

    output = asyncio.run(fetch_webpage(url="https://example.com/captain-search", format="markdown"))

    events = _read_events()
    fallback_start = _last_event(events, "fetch_fallback_start")
    fallback_result = _last_event(events, "fetch_fallback_result")
    finish = _last_event(events, "tool_finish")

    assert fallback_start["reason"] == "upstream timeout"
    assert fallback_result["title"] == "Captain Search"
    assert finish["used_fallback"] is True
    assert "Updated documentation body" in finish["result"]
    assert output.startswith("# Captain Search")


def test_summary_mode_raw_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPTAIN_SEARCH_LOG_FULL_PAYLOADS", "false")
    reset_config()

    patch_search_provider_factory(
        monkeypatch,
        providers={
            "exa_mcp": StaticSearchProvider(
                results=lambda query, max_results: [
                    search_result(
                        title="Captain Search alternative",
                        url="https://example.com/alt",
                        content=f"query={query}; max_results={max_results}",
                        source="exa_mcp",
                    )
                ]
            )
        },
    )

    output = asyncio.run(
        search_web(
            query="captain search alternatives",
            max_results=1,
            format="json",
            provider="exa_mcp",
        )
    )

    events = _read_events()
    provider_result = _event(events, "provider_result", provider="exa_mcp")
    finish = _event(events, "tool_finish")

    assert provider_result.get("request", {}).get("query") == "captain search alternatives"
    assert provider_result.get("raw_results")
    assert finish.get("raw_result") == output