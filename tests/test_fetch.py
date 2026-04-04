"""Behavior tests for fetch_webpage."""

from __future__ import annotations

import asyncio
import json

import pytest

from captain_search.tools import fetch_webpage
from tests._helpers import (
    FETCH_PROVIDER_NAMES,
    fetch_response,
    make_config,
    patch_fetch_providers,
    provider_settings,
)


@pytest.mark.parametrize("provider_name", FETCH_PROVIDER_NAMES, ids=FETCH_PROVIDER_NAMES)
def test_provider_selection(monkeypatch: pytest.MonkeyPatch, provider_name: str) -> None:
    title = f"{provider_name} extract"
    content = f"{provider_name} extracted content"
    config = make_config(
        providers={
            provider_name: provider_settings(
                enabled=True,
                api_key="test-key" if provider_name != "jina" else None,
                weight=50,
            ),
        }
    )
    patch_fetch_providers(
        monkeypatch,
        config=config,
        providers={
            provider_name: fetch_response(
                url="https://example.com",
                title=title,
                content=content,
            ),
        },
    )

    output = asyncio.run(fetch_webpage(url="https://example.com", format="markdown"))

    assert output.startswith(f"# {title}")
    assert content in output


def test_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        providers={
            "parallel": provider_settings(enabled=True, api_key="test-key", weight=40),
            "jina": provider_settings(enabled=True, weight=20),
        }
    )
    patch_fetch_providers(
        monkeypatch,
        config=config,
        selected="parallel",
        providers={
            "parallel": fetch_response(
                url="https://example.com",
                title="",
                content="",
                error="parallel timeout",
            ),
            "jina": fetch_response(
                url="https://example.com",
                title="Jina Reader",
                content="Jina fallback content",
            ),
        },
    )

    output = asyncio.run(fetch_webpage(url="https://example.com", format="markdown"))

    assert output.startswith("# Jina Reader")
    assert "Jina fallback content" in output


def test_json_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        providers={
            "parallel": provider_settings(enabled=False),
            "jina": provider_settings(enabled=True, weight=20),
        }
    )
    patch_fetch_providers(
        monkeypatch,
        config=config,
        providers={
            "jina": fetch_response(
                url="https://example.com/docs",
                title="Example Documentation",
                content="# Example Documentation\n\nThis is the extracted content.",
                status=200,
            )
        },
    )

    output = asyncio.run(fetch_webpage(url="https://example.com/docs", format="json"))

    payload = json.loads(output)
    assert payload == {
        "url": "https://example.com/docs",
        "title": "Example Documentation",
        "status": 200,
        "content_length": 55,
        "content": "# Example Documentation\n\nThis is the extracted content.",
    }


def test_json_error(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        providers={
            "parallel": provider_settings(enabled=False),
            "jina": provider_settings(enabled=True, weight=20),
        }
    )
    patch_fetch_providers(
        monkeypatch,
        config=config,
        providers={
            "jina": fetch_response(
                url="https://example.com/docs",
                title="",
                content="",
                error="upstream timeout",
            )
        },
        fallback=fetch_response(
            url="https://example.com/docs",
            title="",
            content="",
            status=404,
            error="Download: HTTP 404",
        ),
    )

    output = asyncio.run(fetch_webpage(url="https://example.com/docs", format="json"))

    payload = json.loads(output)
    assert payload == {
        "url": "https://example.com/docs",
        "title": "",
        "status": 404,
        "content_length": 0,
        "content": "",
        "error": "Failed to fetch the requested URL. Check Captain Search logs for provider-specific errors.",
    }


def test_public_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_fetch_providers(
        monkeypatch,
        config=make_config(
            providers={
                "parallel": provider_settings(enabled=False),
                "jina": provider_settings(enabled=True),
            }
        ),
        providers={
            "jina": fetch_response(
                url="https://factoryberlin.com/handbook",
                title="Error",
                content="Target URL returned error 404",
            )
        },
        fallback=fetch_response(
            url="https://factoryberlin.com/handbook",
            title="",
            content="",
            error=(
                "Download: Client error '404 Not Found' for url "
                "'https://factoryberlin.com/handbook'"
            ),
        ),
    )

    output = asyncio.run(fetch_webpage(url="https://factoryberlin.com/handbook", format="markdown"))

    assert output == (
        "**Error:** Failed to fetch the requested URL. "
        "Check Captain Search logs for provider-specific errors."
    )
    assert "404" not in output
    assert "factoryberlin.com" not in output


def test_github_blob_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(self, url: str, format: str = "markdown"):
        del self
        return fetch_response(
            url=url,
            title="Normalized URL",
            content=url,
            format=format,
        )

    patch_fetch_providers(
        monkeypatch,
        config=make_config(
            providers={
                "parallel": provider_settings(enabled=False),
                "jina": provider_settings(enabled=True),
            }
        ),
        providers={"jina": fake_fetch},
    )

    output = asyncio.run(
        fetch_webpage(
            url="https://github.com/mnm-matin/captain-search/blob/main/README.md",
            format="markdown",
        )
    )

    assert "https://raw.githubusercontent.com/mnm-matin/captain-search/main/README.md" in output