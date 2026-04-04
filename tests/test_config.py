"""Config normalization tests."""

from __future__ import annotations

import pytest

from captain_search.config import get_config, reset_config
from tests._helpers import clear_provider_envs


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_provider_envs(monkeypatch)
    reset_config()
    yield
    reset_config()


def test_api_key_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "")
    monkeypatch.setenv("SERPER_API_KEYS", "alpha,beta")
    monkeypatch.setenv("TAVILY_API_KEY", "gamma")
    monkeypatch.setenv("TAVILY_API_KEYS", "delta, epsilon")
    reset_config()

    config = get_config()

    assert config.providers.serper.api_keys == ["alpha", "beta"]
    assert config.providers.serper.api_key == "alpha"
    assert config.providers.tavily.api_keys == ["gamma", "delta", "epsilon"]
    assert config.providers.tavily.api_key == "gamma"


def test_exa_keys_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "primary")
    monkeypatch.setenv("EXA_API_KEYS", "secondary")
    reset_config()

    config = get_config()

    assert config.providers.exa.api_keys == ["primary", "secondary"]
    assert config.providers.exa.api_key == "primary"
    assert config.providers.exa_mcp.api_keys == ["primary", "secondary"]
    assert config.providers.exa_mcp.api_key == "primary"