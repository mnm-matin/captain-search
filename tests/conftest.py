"""Shared pytest fixtures for Captain Search tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from captain_search.config import reset_config
from captain_search.health import reset_health_registry
from tests._live_provider_audit import (
    get_session_live_provider_report,
    render_live_provider_summary,
)


@pytest.fixture(autouse=True)
def isolate_health_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CAPTAIN_SEARCH_LOG_DIR", str(tmp_path / "logs"))
    reset_config()
    reset_health_registry(remove_state=True)
    yield
    reset_config()
    reset_health_registry(remove_state=True)


@pytest.fixture(autouse=True)
def disable_github_code_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_github_provider(timeout: float = 30.0):
        del timeout
        return None

    monkeypatch.setattr(
        "captain_search.tools.code_search._get_github_provider",
        fake_get_github_provider,
    )


def pytest_terminal_summary(terminalreporter, exitstatus: int, config) -> None:
    del exitstatus
    report = get_session_live_provider_report(config)
    if report is None:
        return

    terminalreporter.write_sep("-", "Captain Search Live Provider Audit")
    for line in render_live_provider_summary(report).splitlines():
        terminalreporter.write_line(line)