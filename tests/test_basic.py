"""Basic smoke tests for public tools."""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from captain_search.tools import fetch_webpage, search_code, search_web

QUERY = "openai api"
FETCH_URL = "https://example.com"
CODE_QUERY = "contextmanager"
NO_PROVIDERS_ERROR = "No search providers configured"
AUTH_ERROR_MARKERS = ["Invalid API key", "Access forbidden", "HTTP 401", "HTTP 403"]


def test_imports():
    """Test that all modules can be imported."""
    from captain_search import __version__
    from captain_search.config import Config, get_config  # noqa: F401
    from captain_search.providers import (
        BraveProvider,  # noqa: F401
        JinaProvider,  # noqa: F401
        PerplexityProvider,  # noqa: F401
        SearchProvider,  # noqa: F401
        SearchResult,  # noqa: F401
        SerperProvider,  # noqa: F401
        TavilyProvider,  # noqa: F401
    )
    from captain_search.tools import fetch_webpage, search_code, search_web  # noqa: F401

    assert isinstance(__version__, str)
    assert __version__


def _skip_if_no_e2e() -> None:
    if not os.getenv("RUN_E2E"):
        pytest.skip("Set RUN_E2E=1 to run networked smoke tests")


def test_search_web_smoke() -> None:
    _skip_if_no_e2e()

    output = asyncio.run(search_web(query=QUERY, max_results=1, format="json"))
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as e:
        pytest.fail(f"search_web returned non-JSON output: {output[:200]} ({e})")
    error = payload.get("error")

    if error and NO_PROVIDERS_ERROR in error:
        pytest.skip("No web providers configured")
    if error and any(marker in error for marker in AUTH_ERROR_MARKERS):
        pytest.skip("Web provider authentication not configured")

    assert not error, f"search_web error: {error}"
    assert payload["results"], "No search results returned"


def test_fetch_webpage_smoke() -> None:
    _skip_if_no_e2e()

    output = asyncio.run(fetch_webpage(url=FETCH_URL, format="markdown"))
    assert not output.startswith("**Error:**")
    assert "Example Domain" in output


def test_search_code_smoke() -> None:
    _skip_if_no_e2e()

    output = asyncio.run(search_code(query=CODE_QUERY))
    assert output.strip()
    assert output.strip() != "No results found."
