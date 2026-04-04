"""Install the Captain Search CLI skill for agent runtimes."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

SKILL_NAME = "captain-search-cli"


@dataclass(frozen=True)
class InstalledSkill:
    """Details about an installed Captain Search skill."""

    skill_dir: Path
    skill_file: Path
    scope: str
    target: str
    runtime: str
    command_prefix: tuple[str, ...]


def install_skill(
    *,
    scope: str = "user",
    target: str = "auto",
    runtime: str = "auto",
    force: bool = False,
    cwd: Path | None = None,
    home: Path | None = None,
) -> InstalledSkill:
    """Install the Captain Search skill into an agent skill directory."""

    working_dir = (cwd or Path.cwd()).resolve()
    home_dir = (home or Path.home()).resolve()
    resolved_target = _resolve_target(target=target, scope=scope, cwd=working_dir, home=home_dir)
    resolved_runtime, command_prefix = _resolve_runtime(runtime)

    skill_dir = _resolve_skill_dir(
        scope=scope,
        target=resolved_target,
        cwd=working_dir,
        home=home_dir,
    )
    skill_file = skill_dir / "SKILL.md"

    if skill_dir.exists() and not force:
        raise FileExistsError(
            f"Captain Search skill already exists at {skill_dir}. Re-run with --force to overwrite it."
        )

    skill_dir.mkdir(parents=True, exist_ok=True)

    rendered_files = _render_skill_files(command_prefix=command_prefix, runtime=resolved_runtime)
    for relative_path, content in rendered_files.items():
        file_path = skill_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    return InstalledSkill(
        skill_dir=skill_dir,
        skill_file=skill_file,
        scope=scope,
        target=resolved_target,
        runtime=resolved_runtime,
        command_prefix=command_prefix,
    )


def _resolve_target(*, target: str, scope: str, cwd: Path, home: Path) -> str:
    if target in {"agents", "claude"}:
        return target
    if target != "auto":
        raise ValueError(f"Unsupported skill target: {target}")

    agents_dir = _resolve_skill_dir(scope=scope, target="agents", cwd=cwd, home=home).parent
    claude_dir = _resolve_skill_dir(scope=scope, target="claude", cwd=cwd, home=home).parent

    if agents_dir.exists():
        return "agents"
    if claude_dir.exists():
        return "claude"
    return "agents"


def _resolve_runtime(runtime: str) -> tuple[str, tuple[str, ...]]:
    if runtime == "auto":
        repo_root = _find_repo_root()
        if repo_root is not None:
            return "repo", ("uv", "run", "--directory", str(repo_root), "csearch")
        return "uvx", ("uvx", "--from", "captain-search", "csearch")

    if runtime == "repo":
        repo_root = _find_repo_root()
        if repo_root is None:
            raise ValueError(
                "The repo runtime is only available from a Captain Search source checkout."
            )
        return runtime, ("uv", "run", "--directory", str(repo_root), "csearch")

    if runtime == "uvx":
        return runtime, ("uvx", "--from", "captain-search", "csearch")
    if runtime == "installed":
        return runtime, ("csearch",)
    raise ValueError(f"Unsupported skill runtime: {runtime}")


def _find_repo_root() -> Path | None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "skills" / SKILL_NAME / "SKILL.md").is_file():
            return parent
    return None


def _resolve_skill_dir(*, scope: str, target: str, cwd: Path, home: Path) -> Path:
    if scope == "user":
        root = home
    elif scope == "project":
        root = cwd
    else:
        raise ValueError(f"Unsupported skill scope: {scope}")

    if target == "agents":
        return root / ".agents" / "skills" / SKILL_NAME
    if target == "claude":
        return root / ".claude" / "skills" / SKILL_NAME
    raise ValueError(f"Unsupported skill target: {target}")


def _render_skill_files(*, command_prefix: tuple[str, ...], runtime: str) -> dict[Path, str]:
    command = shlex.join(command_prefix)
    runtime_label = {
        "repo": "repo checkout",
        "uvx": "uvx package",
        "installed": "installed CLI",
    }[runtime]
    runtime_note = {
        "repo": (
            "This skill runs Captain Search from the current source checkout with "
            "`uv run --directory ... csearch ...`."
        ),
        "uvx": (
            "This skill shells out through `uvx --from captain-search csearch ...`, "
            "so it does not require a persistent install."
        ),
        "installed": "This skill calls the installed `csearch` executable directly.",
    }[runtime]

    skill_md = dedent(
        f"""\
        ---
        name: captain-search-cli
        description: Use Captain Search from the terminal when the user needs exact csearch commands, CLI-first onboarding, web search, repo-scoped code search, webpage extraction, provider diagnosis, or a reusable skill install. Prefer this skill for direct CLI workflows. Only switch to MCP when the user explicitly asks for MCP setup.
        ---

        # Captain Search CLI

        Use this skill for direct terminal work with Captain Search.

        ## Resolve the entrypoint

        1. Use `{command} ...` for Captain Search commands.
        2. This install uses the `{runtime_label}` runtime.
        3. {runtime_note}
        4. Bare `csearch` prints help and exits `0`. Use `mcp` explicitly for server mode.

        ## Pick the workflow

        1. For first-run install, smoke tests, or the recommended progression, read `references/onboarding.md`.
        2. For exact commands, output formats, and CLI rules, read `references/commands.md`.
        3. For provider trouble, empty results, or rate limits, run `{command} doctor` before assuming a backend is broken.

        ## Non-negotiable CLI rules

        1. Use the short subcommands: `web`, `code`, `fetch`, `doctor`, `skill`, `mcp`, `version`.
        2. Do not use legacy `search-web`, `search-code`, `fetch-webpage`, or `serve` examples.
        3. Use `web --all` for breadth. Do not use `--provider multi` or `--provider all`.
        4. `web`, `code`, and `fetch` all support `--format json`.
        5. Treat exit code `0` as top-level success only. Provider-level warnings or partial failures can still appear in the output.

        ## Route quickly

        - Live web results or provider fan-out: use `web`.
        - Repository-aware code lookup: use `code`.
        - HTML, GitHub blob URLs, PDFs, or docs extraction: use `fetch`.
        - Provider health and cooldown inspection: use `doctor`.
        - Skill install or refresh: use `skill install`.
        - MCP server launch: use `mcp` only when explicitly requested.

        ## Minimal examples

        ```bash
        {command} web "openai api" --max-results 5
        {command} code "search_web" --repo mnm-matin/captain-search --format json
        {command} fetch https://example.com --format json
        {command} doctor
        ```
        """
    )

    onboarding_md = dedent(
        f"""\
        # Captain Search Onboarding

        Use this flow when someone wants to start using the CLI quickly without sitting through every provider and MCP option first.

        ## Recommended flow

        1. Start with the smallest working path: `{command} web ...`.
        2. Ask only for credentials that matter right now.
        3. Prove the install with one command before explaining advanced options.
        4. Expand to `fetch` and `code` only after the first command works.
        5. Move to `mcp` only if the user explicitly asks for MCP setup.

        ## Minimal smoke-test sequence

        ```bash
        {command} web "github actions cache" --max-results 5
        {command} fetch https://github.com/mnm-matin/captain-search/blob/main/README.md
        {command} code "search_web" --repo mnm-matin/captain-search --format json
        ```

        ## Best default onboarding script

        1. Ask whether the user wants one-off CLI usage, a persistent local install, a reusable skill install, or MCP setup.
        2. If the answer is CLI usage, stay in CLI mode and avoid MCP instructions.
        3. Get one successful `web` command on screen.
        4. Then ask whether they also need code search, webpage extraction, provider-specific tuning, or MCP server setup.
        5. Only after that, explain additional provider keys, logs, and persistent installs.

        ## What not to do

        1. Do not lead with a long API-key checklist.
        2. Do not explain every supported entrypoint before the first successful result.
        3. Do not mix CLI onboarding with MCP client setup unless the user explicitly asks for both.
        4. Do not assume `code` or `fetch` require the same credentials as `web`.

        ## Troubleshooting order

        1. Run `{command} doctor`.
        2. Retry the smallest failing command.
        3. Inspect `~/.captain-search/logs` if the output is empty, partial, or rate-limited.
        4. Add provider-specific keys only after confirming which provider path is actually failing.
        """
    )

    commands_md = dedent(
        f"""\
        # Captain Search Commands

        Use this reference when you need an exact command instead of a high-level explanation.

        ## Entry point

        1. This skill uses `{command} ...`.
        2. If the user later switches runtimes, re-run `{command} skill install --force` with the right `--runtime` value.
        3. `captain-search ...` is equivalent to `csearch ...` when the longer name is installed.

        ## web

        1. Use `web` for live web results.
        2. Omit `--provider` to use `auto`.
        3. Use `--all` to query all enabled providers in parallel.
        4. Use a comma-separated `--provider` list to run a specific set of providers.
        5. Valid provider names are `serper`, `brave`, `tavily`, `perplexity`, `parallel`, `exa`, and `exa_mcp`.
        6. `--all` and `--provider` are mutually exclusive.
        7. `--max-results` accepts `1-50`.
        8. `--format` accepts `markdown` or `json`.

        Examples:

        ```bash
        {command} web "openai api" --provider brave --format json
        {command} web "python site:docs.python.org asyncio" --max-results 8
        {command} web "react server actions" --all --max-results 10
        ```

        ## code

        1. Add `--repo` whenever repository scope matters.
        2. Pass `--repo` as `owner/repo`, a Git URL, a local path, or a `file://` local path.
        3. Without `--repo`, only remote-scope providers run.
        4. `--format` accepts `markdown` or `json`.
        5. `No results found.` is a valid result, not a shell failure.

        Examples:

        ```bash
        {command} code "search_web" --repo mnm-matin/captain-search
        {command} code "FastMCP" --repo https://github.com/mnm-matin/captain-search --format json
        ```

        ## fetch

        1. Use `fetch` for HTML pages, GitHub blob URLs, PDFs, and other documents.
        2. Use `--format markdown` by default.
        3. Use `--format json` when you need URL, title, status, and content length alongside the content.

        Examples:

        ```bash
        {command} fetch https://example.com --format json
        {command} fetch https://github.com/mnm-matin/captain-search/blob/main/README.md
        ```

        ## doctor

        1. Use `doctor` when providers appear disabled, empty, cooling down, or rate-limited.

        Example:

        ```bash
        {command} doctor
        ```

        ## skill install

        1. Use `skill install` to install or refresh this agent skill.
        2. `--scope user` installs under the home directory. `--scope project` installs under the current working directory.
        3. `--target auto` prefers `.agents/skills` and falls back to `.claude/skills` only if that is already present.
        4. Use `--target claude` when the user explicitly wants Claude Code skills.
        5. Use `--runtime repo`, `--runtime uvx`, or `--runtime installed` when the generated commands need to match a specific runtime.
        6. Use `--force` to overwrite an existing skill install.

        Examples:

        ```bash
        {command} skill install
        {command} skill install --scope project --target claude --force
        ```

        ## mcp

        1. Use `mcp` to run the MCP server.
        2. `mcp` accepts `--transport`, `--host`, and `--port`.
        3. Bare `csearch` no longer starts the server.

        Examples:

        ```bash
        {command} mcp
        {command} mcp --transport http --port 8000 --host 0.0.0.0
        ```

        ## version

        1. Use `version` to print the CLI version without needing a global flag.

        Example:

        ```bash
        {command} version
        ```
        """
    )

    return {
        Path("SKILL.md"): skill_md,
        Path("references") / "onboarding.md": onboarding_md,
        Path("references") / "commands.md": commands_md,
    }