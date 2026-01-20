"""End-to-end provider health checks."""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from captain_search.config import get_config, reset_config
from captain_search.providers import NoodlProvider
from captain_search.tools import search_code, search_web

QUERY = "openai api"
MAX_RESULTS_PER_PROVIDER = 1
PROVIDERS = ["serper", "brave", "tavily", "perplexity", "exa", "exa_mcp"]
AUTH_ERROR_MARKERS = ["Invalid API key", "Access forbidden", "HTTP 401", "HTTP 403"]
GLOBAL_CODE_QUERY = "contextmanager"
REPO_CODE_QUERY = "search_web"
CODE_REPO = "mnm-matin/captain-search"
CODE_SECTIONS = [
    ("exa_mcp", "## Exa Code Context"),
    ("grep_app", "## grep.app"),
    ("deepwiki", "## DeepWiki"),
    ("noodl", "## Noodl"),
]


async def _check_provider(provider: str, enabled_providers: set[str]) -> dict[str, str]:
    output = await search_web(
        query=QUERY,
        max_results=MAX_RESULTS_PER_PROVIDER,
        provider=provider,
        format="json",
    )
    payload = json.loads(output)
    error = payload.get("error")
    results = payload["results"]

    if provider not in enabled_providers:
        return {
            "provider": provider,
            "status": "not_configured",
            "details": "API key missing or provider disabled",
        }
    if error:
        if any(marker in error for marker in AUTH_ERROR_MARKERS):
            return {
                "provider": provider,
                "status": "not_tested",
                "details": "API key invalid or unauthorized",
            }
        return {"provider": provider, "status": "failed", "details": error}
    if not results:
        return {"provider": provider, "status": "failed", "details": "No results returned"}
    return {
        "provider": provider,
        "status": "ok",
        "details": f"{len(results)} results",
    }


def _render_matrix(rows: list[dict[str, str]]) -> str:
    lines = ["| Provider | Status | Details |", "|---|---|---|"]
    for row in rows:
        details = row["details"].replace("|", "\\|")
        lines.append(f"| {row['provider']} | {row['status']} | {details} |")
    return "\n".join(lines)


def _skip_if_no_e2e() -> None:
    if not os.getenv("RUN_E2E"):
        pytest.skip("Set RUN_E2E=1 to run provider e2e tests")


def test_web_providers_e2e_matrix() -> None:
    _skip_if_no_e2e()
    reset_config()
    enabled = set(get_config().get_enabled_providers())

    async def run_checks() -> list[dict[str, str]]:
        rows = []
        for provider in PROVIDERS:
            rows.append(await _check_provider(provider, enabled))
        return rows

    rows = asyncio.run(run_checks())
    matrix = _render_matrix(rows)
    print("\n" + matrix)

    failures = [row for row in rows if row["status"] == "failed"]
    assert not failures, f"Some providers failed:\n{matrix}"


def _check_code_providers(
    output_global: str,
    output_repo: str,
    noodl_available: bool,
) -> list[dict[str, str]]:
    rows = []
    for provider, section in CODE_SECTIONS:
        output = output_global if provider in {"exa_mcp", "grep_app"} else output_repo
        if provider == "noodl" and not noodl_available:
            rows.append(
                {
                    "provider": provider,
                    "status": "not_configured",
                    "details": "noodl CLI not installed",
                }
            )
            continue

        if section in output:
            rows.append({"provider": provider, "status": "ok", "details": "section present"})
            continue

        status = "failed" if provider in {"exa_mcp", "grep_app"} else "not_tested"
        rows.append({"provider": provider, "status": status, "details": "No results returned"})

    return rows


def test_code_providers_e2e_matrix() -> None:
    _skip_if_no_e2e()
    output_global = asyncio.run(search_code(query=GLOBAL_CODE_QUERY))
    output_repo = asyncio.run(search_code(query=REPO_CODE_QUERY, repo=CODE_REPO))
    noodl_available = NoodlProvider().is_available()
    rows = _check_code_providers(output_global, output_repo, noodl_available)
    matrix = _render_matrix(rows)
    print("\n" + matrix)

    failures = [row for row in rows if row["status"] == "failed"]
    assert not failures, f"Some code providers failed:\n{matrix}"
