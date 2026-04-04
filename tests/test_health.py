"""Tests for generic key rotation, health-aware cooldowns, and doctor reporting."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from captain_search.doctor import doctor_report
from captain_search.health import get_health_state_path
from captain_search.providers.base import SearchResult
from captain_search.providers.serper import SerperProvider
from captain_search.telemetry import log_event
from captain_search.tools.search import search_web
from tests._helpers import clear_provider_envs, patch_search_provider_factory


def _rate_limited_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.com/search")
    response = httpx.Response(429, headers={"Retry-After": "120"}, request=request)
    return httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)


def _doctor_row(report: str, provider: str) -> str:
    return next(line for line in report.splitlines() if line.startswith(f"| {provider} |"))


@pytest.fixture(autouse=True)
def clear_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_provider_envs(monkeypatch)
    yield


def test_key_rotation() -> None:
    provider = SerperProvider(api_keys=["one", "two"])

    first = provider.choose_api_key(error_message="missing")
    provider.record_http_error(_rate_limited_error())
    second = provider.choose_api_key(error_message="missing")

    assert first == "one"
    assert second == "two"
    assert get_health_state_path().exists()


def test_provider_cooldown_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    call_counts = {"serper": 0, "brave": 0}

    class WeightedConfig:
        def get_provider_weights(self) -> dict[str, int]:
            return {"serper": 2, "brave": 1}

    class CooldownAwareProvider:
        def __init__(self, name: str, *, error: Exception | None = None):
            self.name = name
            self.error = error

        async def search(self, query: str, max_results: int = 10):
            del query, max_results
            call_counts[self.name] += 1
            if self.error is not None:
                raise self.error
            return [
                SearchResult(
                    title="Captain Search result",
                    url="https://search.brave.com/result",
                    content="captain search result",
                    source=self.name,
                )
            ]

        def record_http_error(self, error: httpx.HTTPStatusError) -> None:
            from captain_search.health import get_health_registry

            get_health_registry().record_http_failure(
                self.name,
                status_code=error.response.status_code,
                retry_after=error.response.headers.get("Retry-After"),
            )

        async def close(self) -> None:
            return None

    patch_search_provider_factory(
        monkeypatch,
        config=WeightedConfig(),
        providers={
            "serper": CooldownAwareProvider("serper", error=_rate_limited_error()),
            "brave": CooldownAwareProvider("brave"),
        },
    )
    monkeypatch.setattr(
        "captain_search.tools.search._weighted_random_choice",
        lambda weights: "serper" if "serper" in weights else next(iter(weights)),
    )

    first = json.loads(asyncio.run(search_web(query="captain search", max_results=1, format="json")))
    second = json.loads(asyncio.run(search_web(query="captain search", max_results=1, format="json")))

    assert first["results"][0]["title"] == "Captain Search result"
    assert second["results"][0]["title"] == "Captain Search result"
    assert call_counts["serper"] == 1
    assert call_counts["brave"] >= 1


def test_doctor_cooldowns() -> None:
    from captain_search.health import get_health_registry

    get_health_registry().record_http_failure(
        "serper",
        status_code=429,
        retry_after="120",
        api_key="one",
    )
    log_event("provider_result", provider="serper", result_count=0, error="serper: Rate limit exceeded")

    output = doctor_report()

    assert "# Captain Search Doctor" in output
    assert "| serper |" in output
    assert "Key Cooldowns" in output


def test_doctor_github_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "captain_search.doctor.get_gh_cli_auth_state",
        lambda: (True, True),
    )

    output = doctor_report()

    row = _doctor_row(output, "github_code_search")
    assert "| yes |" in row
    assert "| 1 |" in row
    assert "| healthy |" in row


def test_doctor_github_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "captain_search.doctor.get_gh_cli_auth_state",
        lambda: (False, False),
    )

    output = doctor_report()

    row = _doctor_row(output, "github_code_search")
    assert "| no |" in row
    assert "| 0 |" in row
    assert "| unavailable |" in row