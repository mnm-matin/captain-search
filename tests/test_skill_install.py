"""Tests for Captain Search skill installation."""

from __future__ import annotations

import shlex

import pytest

from captain_search.skill_installer import SKILL_NAME, install_skill


def test_install_skill_writes_expected_files(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    installation = install_skill(
        scope="user",
        target="agents",
        runtime="repo",
        home=home,
        cwd=tmp_path,
    )

    skill_dir = home / ".agents" / "skills" / SKILL_NAME
    assert installation.skill_dir == skill_dir
    assert installation.runtime == "repo"
    assert installation.skill_file == skill_dir / "SKILL.md"

    skill_text = installation.skill_file.read_text(encoding="utf-8")
    assert shlex.join(installation.command_prefix) in skill_text
    assert "references/onboarding.md" in skill_text
    assert (skill_dir / "references" / "commands.md").is_file()
    assert (skill_dir / "references" / "onboarding.md").is_file()


def test_install_skill_requires_force_to_overwrite(tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    install_skill(scope="user", target="agents", runtime="uvx", home=home, cwd=tmp_path)

    with pytest.raises(FileExistsError):
        install_skill(scope="user", target="agents", runtime="uvx", home=home, cwd=tmp_path)

    installation = install_skill(
        scope="user",
        target="agents",
        runtime="installed",
        force=True,
        home=home,
        cwd=tmp_path,
    )

    skill_text = installation.skill_file.read_text(encoding="utf-8")
    assert installation.runtime == "installed"
    assert "This skill calls the installed `csearch` executable directly." in skill_text