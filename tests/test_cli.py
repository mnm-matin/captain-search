"""CLI regression tests for Captain Search."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from captain_search import server


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(["mcp"], {"transport": "stdio"}, id="stdio-default"),
        pytest.param(
            ["mcp", "--transport", "http", "--port", "8123", "--host", "127.0.0.1"],
            {"transport": "http", "host": "127.0.0.1", "port": 8123},
            id="http-mcp-subcommand",
        ),
    ],
)
def test_mcp_start(monkeypatch, argv: list[str], expected: dict[str, object]) -> None:
    seen: dict[str, object] = {}

    def fake_run(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(
        server,
        "config",
        SimpleNamespace(get_enabled_providers=lambda: ["exa_mcp"]),
    )
    monkeypatch.setattr(server.mcp, "run", fake_run)

    exit_code = server.main(argv)

    assert exit_code == 0
    assert seen == expected


def test_no_subcommand_shows_help(capsys) -> None:
    exit_code = server.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage: csearch" in captured.out
    assert captured.err == ""


def test_legacy_flags_rejected(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        server.main(["--transport", "http"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "a subcommand is required; use 'mcp' before server flags" in captured.err


def test_cli_web(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}

    async def fake_search_web(
        query: str,
        max_results: int,
        provider: str | None,
        format: str,
    ) -> str:
        seen.update(
            {
                "query": query,
                "max_results": max_results,
                "provider": provider,
                "format": format,
            }
        )
        return '{"results": [], "error": "Unknown provider(s): nope"}'

    monkeypatch.setattr(server, "web_impl", fake_search_web)

    exit_code = server.main(
        ["web", "openai api", "--max-results", "3", "--provider", "nope", "--format", "json"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == '{"results": [], "error": "Unknown provider(s): nope"}\n'
    assert seen == {
        "query": "openai api",
        "max_results": 3,
        "provider": "nope",
        "format": "json",
    }


def test_cli_web_invalid_max_results(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        server.main(["web", "openai api", "--max-results", "0"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "max-results must be between 1 and 50" in captured.err


def test_cli_web_all_flag(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}

    async def fake_search_web(
        query: str,
        max_results: int,
        provider: str | None,
        format: str,
    ) -> str:
        seen.update(
            {
                "query": query,
                "max_results": max_results,
                "provider": provider,
                "format": format,
            }
        )
        return "## 1. Parallel result\n**URL:** https://parallel.ai"

    monkeypatch.setattr(server, "web_impl", fake_search_web)

    exit_code = server.main(["web", "openai api", "--all"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Parallel result" in captured.out
    assert seen == {
        "query": "openai api",
        "max_results": 10,
        "provider": "all",
        "format": "markdown",
    }


def test_cli_web_warnings_pass(monkeypatch, capsys) -> None:
    async def fake_search_web(
        query: str,
        max_results: int,
        provider: str | None,
        format: str,
    ) -> str:
        return (
            '{"results": [{"title": "Parallel result", "url": "https://parallel.ai", '
            '"content": "search result"}], "warnings": ["Ignored unknown provider(s): nope"]}'
        )

    monkeypatch.setattr(server, "web_impl", fake_search_web)

    exit_code = server.main(
        ["web", "openai api", "--max-results", "3", "--provider", "parallel,nope", "--format", "json"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert '"warnings": ["Ignored unknown provider(s): nope"]' in captured.out


def test_cli_code(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}

    async def fake_search_code(
        query: str,
        repo: str | None = None,
        format: str = "markdown",
    ) -> str:
        seen.update({"query": query, "repo": repo, "format": format})
        return json.dumps({"query": query}, indent=2)

    monkeypatch.setattr(server, "code_impl", fake_search_code)

    exit_code = server.main(
        ["code", "search_web", "--repo", "mnm-matin/captain-search", "--format", "json"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["query"] == "search_web"
    assert seen == {
        "query": "search_web",
        "repo": "mnm-matin/captain-search",
        "format": "json",
    }


def test_cli_code_error_exit(monkeypatch, capsys) -> None:
    async def fake_search_code(
        query: str,
        repo: str | None = None,
        format: str = "markdown",
    ) -> str:
        del query, repo, format
        return '{"error": "repo resolution failed"}'

    monkeypatch.setattr(server, "code_impl", fake_search_code)

    exit_code = server.main(["code", "search_web", "--format", "json"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "repo resolution failed" in captured.out


def test_cli_fetch(monkeypatch, capsys) -> None:
    seen: dict[str, object] = {}

    async def fake_fetch_webpage(url: str, format: str) -> str:
        seen.update({"url": url, "format": format})
        return json.dumps({"title": "Example Domain"}, indent=2)

    monkeypatch.setattr(server, "fetch_impl", fake_fetch_webpage)

    exit_code = server.main(["fetch", "https://example.com", "--format", "json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["title"] == "Example Domain"
    assert seen == {"url": "https://example.com", "format": "json"}


def test_cli_doctor(monkeypatch, capsys) -> None:
    monkeypatch.setattr(server, "doctor_impl", lambda: "# Captain Search Doctor\n")

    exit_code = server.main(["doctor"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "# Captain Search Doctor\n"


def test_skill_subcommand_shows_help(capsys) -> None:
    exit_code = server.main(["skill"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage: csearch skill" in captured.out
    assert captured.err == ""


def test_cli_skill_install(monkeypatch, capsys, tmp_path) -> None:
    skill_dir = tmp_path / ".agents" / "skills" / "captain-search-cli"

    def fake_install_skill(**kwargs):
        assert kwargs == {
            "scope": "project",
            "target": "claude",
            "runtime": "installed",
            "force": True,
        }
        return SimpleNamespace(
            skill_dir=skill_dir,
            scope="project",
            target="claude",
            runtime="installed",
            command_prefix=("csearch",),
        )

    monkeypatch.setattr(server, "install_skill", fake_install_skill)

    exit_code = server.main(
        [
            "skill",
            "install",
            "--scope",
            "project",
            "--target",
            "claude",
            "--runtime",
            "installed",
            "--force",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Installed Captain Search skill." in captured.out
    assert f"Location: {skill_dir}" in captured.out
    assert "Runtime: installed" in captured.out
    assert captured.err == ""


def test_cli_skill_install_existing_skill(monkeypatch, capsys) -> None:
    def fake_install_skill(**kwargs):
        del kwargs
        raise FileExistsError("Captain Search skill already exists. Re-run with --force.")

    monkeypatch.setattr(server, "install_skill", fake_install_skill)

    exit_code = server.main(["skill", "install"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Re-run with --force" in captured.err
    assert captured.out == ""


def test_cli_version(capsys) -> None:
    exit_code = server.main(["version"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == f"csearch {server.__version__}\n"