"""Morph Warp Grep provider for repo-scoped code search."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from captain_search.providers.base import SearchProvider, SearchResult

DEFAULT_BASE_URL = "https://api.morphllm.com"
DEFAULT_MODEL = "morph-warp-grep-v2.1"
MAX_TOOL_TURNS = 6
MAX_GREP_LINES = 200
MAX_LIST_LINES = 200
MAX_READ_LINES = 800
MAX_GLOB_FILES = 100
MAX_REPO_STRUCTURE_LINES = 200
MAX_TOKENS = 2048

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
    "coverage",
    ".idea",
    ".vscode",
    "venv",
    ".next",
}


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        return normalized
    if path.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _safe_path(repo_root: Path, target: str | None) -> Path | None:
    if not target or target == ".":
        return repo_root
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if resolved == repo_root or repo_root in resolved.parents:
        return resolved
    return None


def _build_repo_structure(repo_path: Path, max_depth: int = 2) -> str:
    root = repo_path.resolve()
    lines = [str(root)]

    def walk(current: Path, depth: int) -> None:
        if depth > max_depth or len(lines) >= MAX_REPO_STRUCTURE_LINES:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda entry: (entry.is_file(), entry.name.lower()))
        except OSError:
            return

        for entry in entries:
            if entry.name.startswith(".") or entry.name in IGNORED_DIRS:
                continue
            lines.append(str(entry.resolve()))
            if len(lines) >= MAX_REPO_STRUCTURE_LINES:
                return
            if entry.is_dir():
                walk(entry, depth + 1)

    walk(root, 0)
    return "\n".join(lines)


def _parse_line_ranges(raw: str | None, total_lines: int) -> list[tuple[int, int]]:
    if not raw or raw.strip() in {"", "*"}:
        return [(1, total_lines)]

    ranges: list[tuple[int, int]] = []
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        if "-" in candidate:
            start_str, end_str = candidate.split("-", 1)
        else:
            start_str = end_str = candidate
        start = max(int(start_str), 1)
        end = max(int(end_str), 1)
        if start > end:
            start, end = end, start
        if start > total_lines:
            continue
        ranges.append((start, min(end, total_lines)))

    return ranges or [(1, total_lines)]


def _read_with_line_numbers(path: Path, ranges: list[tuple[int, int]]) -> str:
    try:
        all_lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return f"[FILE NOT FOUND] {path} does not exist"

    output: list[str] = []
    seen_lines: set[int] = set()
    for start, end in ranges:
        for line_no in range(start, end + 1):
            if line_no in seen_lines or not 1 <= line_no <= len(all_lines):
                continue
            seen_lines.add(line_no)
            output.append(f"{line_no}|{all_lines[line_no - 1]}")
            if len(output) >= MAX_READ_LINES:
                output.append(f"... truncated ({len(all_lines)} total lines)")
                return "\n".join(output)
    return "\n".join(output)


def _iter_files(base_dir: Path, glob_filter: str | None) -> Iterable[Path]:
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [directory for directory in dirs if directory not in IGNORED_DIRS and not directory.startswith(".")]
        for filename in files:
            if glob_filter and not Path(filename).match(glob_filter):
                continue
            yield Path(root) / filename


def _grep_python(pattern: str, base_dir: Path, glob_filter: str | None) -> str:
    regex = re.compile(pattern, re.IGNORECASE)
    results: list[str] = []
    for file_path in _iter_files(base_dir, glob_filter):
        try:
            text_lines = file_path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(text_lines):
            if not regex.search(line):
                continue
            start = max(0, index - 1)
            end = min(len(text_lines) - 1, index + 1)
            for line_index in range(start, end + 1):
                results.append(f"{file_path.resolve()}:{line_index + 1}:{text_lines[line_index]}")
                if len(results) >= MAX_GREP_LINES:
                    return "\n".join(results) + f"\n... (truncated at {MAX_GREP_LINES} lines)"
    return "\n".join(results) if results else "no matches"


def _turn_message(turn: int) -> str:
    remaining = MAX_TOOL_TURNS - turn
    if remaining <= 1:
        return (
            f"You have used {turn} turns, you only have 1 turn remaining. "
            "You have run out of turns to explore the code base and MUST call the finish tool now"
        )
    suffix = "s" if turn != 1 else ""
    return f"You have used {turn} turn{suffix} and have {remaining} remaining"


class MorphWarpGrepProvider(SearchProvider):
    """Morph Warp Grep provider for repo-local code search."""

    name = "morph_warp_grep"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 90.0,
    ):
        super().__init__(api_key=api_key, timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return []

    async def code_search(self, query: str, repo_path: Path) -> list[SearchResult]:
        if not self.api_key:
            raise ValueError("Morph API key is required. Set MORPH_API_KEY.")

        repo_root = repo_path.resolve()
        initial_message = (
            f"<repo_structure>\n{_build_repo_structure(repo_root)}\n</repo_structure>\n\n"
            f"<search_string>\n{query}\n</search_string>"
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": initial_message}]

        for turn in range(1, MAX_TOOL_TURNS + 1):
            assistant_message = await self._call_morph(messages)
            messages.append(assistant_message)

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                break

            finish_call = next(
                (
                    call
                    for call in tool_calls
                    if isinstance(call, dict)
                    and isinstance(call.get("function"), dict)
                    and call["function"].get("name") == "finish"
                ),
                None,
            )
            if finish_call:
                return self._results_from_finish(repo_root, finish_call)

            for call in tool_calls:
                if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                    continue
                tool_output = self._execute_tool(repo_root, call)
                tool_call_id = str(call.get("id") or "")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": tool_output,
                    }
                )

            messages.append({"role": "user", "content": _turn_message(turn)})

        return []

    async def _call_morph(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        client = await self.get_client()
        try:
            response = await client.post(
                _chat_completions_url(self.base_url),
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.0,
                    "max_tokens": MAX_TOKENS,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "captain-search/0.1.0",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                detail = (
                    "Morph endpoint not found. Check MORPH_BASE_URL/MORPH_API_URL and use the "
                    "Warp Grep model on the OpenAI-compatible /v1/chat/completions API."
                )
                raise RuntimeError(detail) from exc
            raise
        data = response.json()
        message = data["choices"][0]["message"]
        return {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls") or [],
        }

    def _execute_tool(self, repo_path: Path, tool_call: dict[str, Any]) -> str:
        function = tool_call["function"]
        name = str(function["name"])
        arguments_text = str(function.get("arguments") or "{}")
        try:
            arguments = json.loads(arguments_text)
        except json.JSONDecodeError:
            return f"Error: invalid JSON arguments for {name}"

        if name == "grep_search":
            return self._run_grep(repo_path, arguments)
        if name == "read":
            return self._run_read(repo_path, arguments)
        if name == "list_directory":
            return self._run_list_directory(repo_path, arguments)
        if name == "glob":
            return self._run_glob(repo_path, arguments)
        return f"Unknown tool: {name}"

    def _run_grep(self, repo_path: Path, arguments: dict[str, Any]) -> str:
        pattern = str(arguments.get("pattern") or "")
        if not pattern:
            return "Error: pattern is required"
        target_path = str(arguments.get("path") or ".")
        glob_filter = str(arguments.get("glob") or "") or None
        safe_dir = _safe_path(repo_path, target_path)
        if not safe_dir or not safe_dir.exists():
            return f"Error: path not found: {target_path}"

        limit = int(arguments.get("limit") or MAX_GREP_LINES)
        rg_path = shutil.which("rg")
        if rg_path:
            command = [
                rg_path,
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "-i",
                "-C",
                "1",
            ]
            if glob_filter:
                command.extend(["--glob", glob_filter])
            command.extend([pattern, str(safe_dir)])
            result = subprocess.run(command, capture_output=True, text=True, cwd=repo_path, check=False)
            if result.returncode not in (0, 1):
                return (result.stderr.strip() or result.stdout.strip() or "Error: grep failed").strip()
            lines = result.stdout.strip().splitlines() if result.stdout.strip() else []
            if limit and len(lines) > limit:
                return "\n".join(lines[:limit]) + f"\n... (truncated at {limit} lines)"
            if len(lines) > MAX_GREP_LINES:
                return "\n".join(lines[:MAX_GREP_LINES]) + f"\n... (truncated at {MAX_GREP_LINES} lines)"
            return result.stdout.strip() if result.stdout.strip() else "no matches"

        return _grep_python(pattern, safe_dir, glob_filter)

    def _run_read(self, repo_path: Path, arguments: dict[str, Any]) -> str:
        path_text = str(arguments.get("path") or "")
        if not path_text:
            return "Error: path is required"
        safe_path = _safe_path(repo_path, path_text)
        if not safe_path or not safe_path.is_file():
            return f"[FILE NOT FOUND] {path_text} does not exist"
        try:
            total_lines = len(safe_path.read_text(errors="replace").splitlines())
        except OSError:
            return f"[FILE NOT FOUND] {path_text} does not exist"
        line_ranges = _parse_line_ranges(
            str(arguments.get("lines")) if arguments.get("lines") is not None else None,
            total_lines,
        )
        return _read_with_line_numbers(safe_path, line_ranges)

    def _run_list_directory(self, repo_path: Path, arguments: dict[str, Any]) -> str:
        command = str(arguments.get("command") or "").strip()
        if not command:
            return "Error: command is required"

        tokens = shlex.split(command)
        path_tokens = [token for token in tokens[1:] if not token.startswith("-") and token not in {"|", "&&"}]
        target_path = path_tokens[0] if path_tokens else "."
        safe_dir = _safe_path(repo_path, target_path)
        if not safe_dir or not safe_dir.exists():
            return f"Error: directory not found: {target_path}"

        lines: list[str] = []

        def walk(current: Path, depth: int = 0) -> None:
            if depth > 3 or len(lines) >= MAX_LIST_LINES:
                return
            try:
                entries = sorted(current.iterdir(), key=lambda entry: (entry.is_file(), entry.name.lower()))
            except OSError:
                return
            for entry in entries:
                if entry.name.startswith(".") or entry.name in IGNORED_DIRS:
                    continue
                indent = "  " * depth
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{indent}{entry.name}{suffix}")
                if len(lines) >= MAX_LIST_LINES:
                    return
                if entry.is_dir():
                    walk(entry, depth + 1)

        if safe_dir.is_file():
            return safe_dir.name
        walk(safe_dir)
        if len(lines) >= MAX_LIST_LINES:
            lines.append(f"... (truncated at {MAX_LIST_LINES} lines)")
        return "\n".join(lines) if lines else "no matches"

    def _run_glob(self, repo_path: Path, arguments: dict[str, Any]) -> str:
        pattern = str(arguments.get("pattern") or "")
        if not pattern:
            return "Error: pattern is required"
        target_path = str(arguments.get("path") or ".")
        safe_dir = _safe_path(repo_path, target_path)
        if not safe_dir or not safe_dir.is_dir():
            return f"Error: directory not found: {target_path}"

        if "/" in pattern or "**" in pattern:
            matches = list(safe_dir.glob(pattern))
        else:
            matches = list(safe_dir.rglob(pattern))

        filtered = [
            match.resolve()
            for match in matches
            if match.is_file() and not any(part in IGNORED_DIRS or part.startswith(".") for part in match.parts)
        ]
        filtered.sort(key=lambda match: match.stat().st_mtime, reverse=True)
        filtered = filtered[:MAX_GLOB_FILES]
        if not filtered:
            return "no matches"
        header = (
            f'Found {len(filtered)} file(s) matching "{pattern}" within {safe_dir.resolve()}, '
            "sorted by modification time (newest first):"
        )
        return f"{header}\n---\n" + "\n".join(str(match) for match in filtered) + "\n---"

    def _results_from_finish(self, repo_path: Path, tool_call: dict[str, Any]) -> list[SearchResult]:
        function = tool_call["function"]
        arguments_text = str(function.get("arguments") or "{}")
        arguments = json.loads(arguments_text)
        files_text = str(arguments.get("files") or "").strip()
        if not files_text:
            return []

        results: list[SearchResult] = []
        for line in files_text.splitlines():
            spec = line.strip()
            if not spec:
                continue
            if ":" in spec and not spec.endswith(":*"):
                path_text, line_spec = spec.rsplit(":", 1)
                if "-" not in line_spec and "," not in line_spec and not line_spec.isdigit():
                    path_text, line_spec = spec, ""
            else:
                path_text, line_spec = spec.replace(":*", ""), ""

            safe_path = _safe_path(repo_path, path_text)
            if not safe_path or not safe_path.is_file():
                continue
            try:
                total_lines = len(safe_path.read_text(errors="replace").splitlines())
            except OSError:
                continue
            content = _read_with_line_numbers(safe_path, _parse_line_ranges(line_spec or None, total_lines))
            if not content:
                continue
            results.append(
                SearchResult(
                    title=safe_path.relative_to(repo_path).as_posix(),
                    url=f"file://{safe_path}",
                    content=content,
                    source=self.name,
                )
            )

        return results