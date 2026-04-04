"""Opt-in network smoke tests for public tools."""

from __future__ import annotations

import asyncio
import json

import pytest

from captain_search.tools import fetch_webpage, search_code, search_web
from tests._helpers import skip_if_no_e2e

QUERY = "openai api"
FETCH_URL = "https://example.com"
CODE_QUERY = "contextmanager"


def test_web_smoke() -> None:
    skip_if_no_e2e()

    output = asyncio.run(search_web(query=QUERY, max_results=1, format="json"))
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        pytest.fail(f"search_web returned non-JSON output: {output[:200]} ({error})")

    if payload.get("error"):
        pytest.skip(f"Web smoke unavailable: {payload['error']}")

    assert payload["results"], "No search results returned"


def test_fetch_smoke() -> None:
    skip_if_no_e2e()

    output = asyncio.run(fetch_webpage(url=FETCH_URL, format="json"))
    payload = json.loads(output)
    if payload.get("error"):
        pytest.skip(f"Fetch smoke unavailable: {payload['error']}")

    assert payload["status"] == 200
    assert "Example Domain" in payload["content"]


def test_code_smoke() -> None:
    skip_if_no_e2e()

    output = asyncio.run(search_code(query=CODE_QUERY, format="json"))
    payload = json.loads(output)
    if not payload.get("sections"):
        pytest.skip("No code search providers returned results")

    assert any(section.get("items") or section.get("content") for section in payload["sections"])
