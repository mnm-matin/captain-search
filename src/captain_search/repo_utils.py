"""Shared repository parsing and resolution helpers."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def parse_repo(repo: str) -> tuple[str, str]:
    repo = repo.strip()
    if repo.startswith(("/", "./", "../", "~")):
        raise ValueError("repo must be a git URL or owner/repo")

    if repo.startswith("git@"):
        host_part, path = repo.split(":", 1)
        host = host_part.split("@", 1)[1]
    elif repo.startswith(("http://", "https://")):
        parsed = urlparse(repo)
        host = parsed.netloc
        path = parsed.path
    else:
        host = "github.com"
        path = repo

    parts = path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError("repo must be in owner/repo format")
    owner, name = parts[0], parts[1].removesuffix(".git")
    full_name = f"{owner}/{name}"
    clone_url = f"https://{host}/{owner}/{name}.git"
    return full_name, clone_url


def parse_git_remote(remote_url: str) -> str | None:
    remote_url = remote_url.strip()
    if not remote_url:
        return None

    if remote_url.startswith("git@"):
        match = re.match(r"git@[^:]+:(.+?)(?:\.git)?$", remote_url)
        if match:
            return match.group(1)
        return None

    if remote_url.startswith(("http://", "https://")):
        parsed = urlparse(remote_url)
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = path.split("/")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return None

    return None


def resolve_local_repo(repo: str) -> Path | None:
    if repo.startswith("file://"):
        parsed = urlparse(repo)
        candidate = Path(parsed.path)
    else:
        candidate = Path(repo).expanduser()

    if not candidate.exists():
        return None

    resolved = candidate.resolve()
    if not resolved.is_dir():
        return None
    return resolved


def read_git_remote(repo_path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "config", "--get", "remote.origin.url"],
        check=False,
        capture_output=True,
        text=True,
    )
    remote = result.stdout.strip()
    return remote or None


def infer_repo_full(repo_path: Path) -> str | None:
    remote = read_git_remote(repo_path)
    if not remote:
        return None
    try:
        repo_full, _ = parse_repo(remote)
    except ValueError:
        return None
    return repo_full


def repo_name_from_path(repo_path: Path) -> str | None:
    git_name = infer_repo_full(repo_path)
    if git_name:
        return git_name

    name = repo_path.name
    if "__" in name:
        return name.replace("__", "/")
    return None