"""FastMCP server for Captain Search."""

from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from captain_search import __version__
from captain_search.auth import build_auth_provider
from captain_search.config import get_config
from captain_search.doctor import doctor_report as doctor_impl
from captain_search.skill_installer import install_skill
from captain_search.tools.code_search import search_code as code_impl
from captain_search.tools.fetch import fetch_webpage as fetch_impl
from captain_search.tools.search import (
    MAX_SEARCH_RESULTS,
    MIN_SEARCH_RESULTS,
)
from captain_search.tools.search import (
    search_web as web_impl,
)

# Initialize config early to validate environment
config = get_config()

# Optional auth for remote MCP deployments
auth_provider = build_auth_provider(config.settings.mcp_auth_token)

# Create FastMCP server
mcp = FastMCP(
    name="captain_search",
    instructions="""
Captain Search MCP Server - Unified web and code search across multiple providers.

Available tools:
- search_web: Search the web using weighted selection with fallback
- search_code: Search code across Exa, grep.app, DeepWiki, Morph, and local exact matches
- fetch_webpage: Fetch and extract content from a webpage or PDF

The server automatically selects providers based on configured weights and handles
failures by trying alternative providers.
""",
    auth=auth_provider,
)


# Tool annotations following MCP best practices

SEARCH_ANNOTATIONS = {
    "title": "Web Search",
    "readOnlyHint": True,  # Does not modify environment
    "destructiveHint": False,  # No destructive operations
    "idempotentHint": True,  # Same args = same result (mostly)
    "openWorldHint": True,  # Interacts with external services
}

CODE_ANNOTATIONS = {
    "title": "Code Search",
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

FETCH_ANNOTATIONS = {
    "title": "Fetch Webpage",
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

CLI_SUBCOMMANDS = ("mcp", "web", "code", "fetch", "doctor", "skill", "version")


@mcp.tool(name="search_web", annotations=SEARCH_ANNOTATIONS)
async def search_web(
    query: Annotated[str, Field(description="Search query", min_length=1, max_length=500)],
    max_results: Annotated[
        int,
        Field(
            description="Maximum number of results (1-50). In multi mode, per provider.",
            ge=1,
            le=50,
        ),
    ] = 10,
    provider: Annotated[
        str | None,
        Field(
            description=(
                "Provider selector: auto (default), multi/all, a provider name, or a comma-separated list."
            )
        ),
    ] = None,
) -> str:
    """
    Search the web using weighted selection or multi-provider search.

    Args:
        query: The search query string
        max_results: Maximum number of results (1-50, default 10). Per provider in multi mode.
        provider: Provider selector (default: auto)

    Returns:
        Search results in markdown format
    """
    provider_value = (provider or "auto").strip().lower()
    return await web_impl(
        query=query,
        max_results=max_results,
        provider=provider_value,
        format="markdown",
    )


@mcp.tool(name="fetch_webpage", annotations=FETCH_ANNOTATIONS)
async def fetch_webpage(
    url: Annotated[str, Field(description="URL to fetch content from")],
) -> str:
    """
    Fetch and extract content from a webpage or PDF.

    Uses Jina Reader to fetch and convert web pages and PDFs to clean text.
    Handles JavaScript-rendered pages and extracts content from PDFs.
    Falls back to Trafilatura extraction if Jina fails.

    Args:
        url: The URL to fetch (web page or PDF)

    Returns:
        Extracted content in markdown format

    Examples:
        - Fetch a webpage: fetch_webpage("https://example.com/article")
        - Fetch a PDF: fetch_webpage("https://example.com/document.pdf")
    """
    # Always use markdown format for agents
    return await fetch_impl(url=url, format="markdown")


@mcp.tool(name="search_code", annotations=CODE_ANNOTATIONS)
async def search_code(
    query: Annotated[
        str,
        Field(
            description="Code search query (e.g., function names, error messages, API usage)",
            min_length=1,
            max_length=500,
        ),
    ],
    repo: Annotated[
        str | None,
        Field(
            description=(
                "Git URL, owner/repo, or local repo path to scope results "
                "(e.g., 'facebook/react' or '/path/to/repo'). "
                "When provided, enables DeepWiki Q&A, Morph, and local exact matching for that repo."
            )
        ),
    ] = None,
) -> str:
    """
    Search code across multiple providers.

    Args:
        query: Code search query string
        repo: Git URL or owner/repo (optional). When provided, results are scoped to this repo.

    Returns:
        Search results in markdown format
    """
    return await code_impl(query=query, repo=repo)


def _add_server_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP/SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP/SSE transport (default: 0.0.0.0)",
    )


def _parse_max_results(value: str) -> int:
    max_results = int(value)
    if MIN_SEARCH_RESULTS <= max_results <= MAX_SEARCH_RESULTS:
        return max_results
    raise argparse.ArgumentTypeError(
        f"max-results must be between {MIN_SEARCH_RESULTS} and {MAX_SEARCH_RESULTS}"
    )


def _build_cli_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Captain Search MCP server and direct CLI",
    )
    parser.set_defaults(cli_prog=prog)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    mcp_parser = subparsers.add_parser("mcp", help="Run the MCP server")
    _add_server_arguments(mcp_parser)
    mcp_parser.set_defaults(handler=_run_server_command)

    web_parser = subparsers.add_parser("web", help="Search the web")
    web_parser.add_argument("query", help="Search query")
    web_parser.add_argument(
        "--max-results",
        type=_parse_max_results,
        default=10,
        help=(
            "Maximum number of results to return "
            f"({MIN_SEARCH_RESULTS}-{MAX_SEARCH_RESULTS}, default: 10)"
        ),
    )
    provider_group = web_parser.add_mutually_exclusive_group()
    provider_group.add_argument(
        "--all",
        action="store_true",
        help="Search all enabled providers in parallel",
    )
    provider_group.add_argument(
        "--provider",
        default=None,
        help="Provider name or comma-separated provider list",
    )
    web_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    web_parser.set_defaults(handler=_run_search_web_command)

    code_parser = subparsers.add_parser("code", help="Search code")
    code_parser.add_argument("query", help="Code search query")
    code_parser.add_argument(
        "--repo",
        default=None,
        help="Optional Git URL, owner/repo, or local repository path",
    )
    code_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    code_parser.set_defaults(handler=_run_search_code_command)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch and extract a webpage or document")
    fetch_parser.add_argument("url", help="URL to fetch")
    fetch_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    fetch_parser.set_defaults(handler=_run_fetch_webpage_command)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Inspect configured providers, recent telemetry, and cooldown state",
    )
    doctor_parser.set_defaults(handler=_run_doctor_command)

    skill_parser = subparsers.add_parser(
        "skill",
        help="Install or refresh the Captain Search agent skill",
    )
    skill_parser.set_defaults(handler=_run_help_command, help_parser=skill_parser)
    skill_subparsers = skill_parser.add_subparsers(dest="skill_command")

    skill_install_parser = skill_subparsers.add_parser(
        "install",
        help="Install the Captain Search CLI skill into .agents/skills or .claude/skills",
    )
    skill_install_parser.add_argument(
        "--scope",
        choices=["user", "project"],
        default="user",
        help="Install under the home directory or the current working directory (default: user)",
    )
    skill_install_parser.add_argument(
        "--target",
        choices=["auto", "agents", "claude"],
        default="auto",
        help="Skill directory target (default: auto)",
    )
    skill_install_parser.add_argument(
        "--runtime",
        choices=["auto", "repo", "uvx", "installed"],
        default="auto",
        help="Command runtime to bake into the installed skill (default: auto)",
    )
    skill_install_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing Captain Search skill install",
    )
    skill_install_parser.set_defaults(handler=_run_skill_install_command)

    version_parser = subparsers.add_parser("version", help="Print version and exit")
    version_parser.set_defaults(handler=_run_version_command)

    return parser


def _resolve_cli_prog(argv: Sequence[str] | None) -> str:
    if argv is not None:
        return "csearch"
    name = Path(sys.argv[0]).name.strip()
    return name or "csearch"


def _write_cli_output(output: str) -> None:
    sys.stdout.write(output)
    if output and not output.endswith("\n"):
        sys.stdout.write("\n")


def _run_help_command(args: argparse.Namespace) -> int:
    args.help_parser.print_help()
    return 0


def _cli_exit_code(output: str, *, output_format: str | None = None) -> int:
    if output_format == "json":
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return 1 if output.lstrip().startswith("**Error:**") else 0
        return 1 if payload.get("error") else 0

    return 1 if output.lstrip().startswith("**Error:**") else 0


def _run_server_command(args: argparse.Namespace) -> int:
    """Run the MCP server."""

    # Show configured providers on startup
    enabled = config.get_enabled_providers()
    if enabled:
        print(f"Captain Search starting with providers: {', '.join(enabled)}", file=sys.stderr)
    else:
        print(
            "Warning: No search providers configured. Set API keys in environment.", file=sys.stderr
        )

    # Run server
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)
    return 0


def _run_search_web_command(args: argparse.Namespace) -> int:
    provider = "all" if args.all else args.provider
    output = asyncio.run(
        web_impl(
            query=args.query,
            max_results=args.max_results,
            provider=provider,
            format=args.format,
        )
    )
    _write_cli_output(output)
    return _cli_exit_code(output, output_format=args.format)


def _run_search_code_command(args: argparse.Namespace) -> int:
    output = asyncio.run(code_impl(query=args.query, repo=args.repo, format=args.format))
    _write_cli_output(output)
    return _cli_exit_code(output, output_format=args.format)


def _run_fetch_webpage_command(args: argparse.Namespace) -> int:
    output = asyncio.run(fetch_impl(url=args.url, format=args.format))
    _write_cli_output(output)
    return _cli_exit_code(output, output_format=args.format)


def _run_doctor_command(args: argparse.Namespace) -> int:
    del args
    _write_cli_output(doctor_impl())
    return 0


def _run_skill_install_command(args: argparse.Namespace) -> int:
    try:
        installation = install_skill(
            scope=args.scope,
            target=args.target,
            runtime=args.runtime,
            force=args.force,
        )
    except (FileExistsError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    _write_cli_output(
        "\n".join(
            [
                "Installed Captain Search skill.",
                f"Location: {installation.skill_dir}",
                f"Scope: {installation.scope}",
                f"Target: {installation.target}",
                f"Runtime: {installation.runtime}",
                f"Command prefix: {shlex.join(installation.command_prefix)}",
            ]
        )
    )
    return 0


def _run_version_command(args: argparse.Namespace) -> int:
    _write_cli_output(f"{args.cli_prog} {__version__}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    parser = _build_cli_parser(_resolve_cli_prog(argv))
    if not argv_list:
        parser.print_help()
        return 0
    if argv_list[0].startswith("-") and argv_list[0] not in {"-h", "--help", "--version"}:
        parser.error("a subcommand is required; use 'mcp' before server flags")
    args = parser.parse_args(argv_list)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
