"""Live provider audits with short-lived cache and session summary."""

from __future__ import annotations

from tests._helpers import skip_if_no_e2e
from tests._live_provider_audit import (
    get_or_run_live_provider_report,
    render_task_matrix,
    task_failures,
)


def _assert_task_health(pytestconfig, task: str) -> None:
    report = get_or_run_live_provider_report(pytestconfig)
    matrix = render_task_matrix(report, task)

    failures = task_failures(report, task, include_builtin=False)
    assert not failures, f"Some configured {task.replace('_', ' ')} providers failed:\n{matrix}"


def test_live_web(pytestconfig) -> None:
    skip_if_no_e2e()
    _assert_task_health(pytestconfig, "web_search")


def test_live_code(pytestconfig) -> None:
    skip_if_no_e2e()
    _assert_task_health(pytestconfig, "code_search")


def test_live_fetch(pytestconfig) -> None:
    skip_if_no_e2e()
    _assert_task_health(pytestconfig, "fetch")
