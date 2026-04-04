"""Shared output cleaning and rendering helpers."""

from __future__ import annotations

import html
import json
import re
from typing import Final

from captain_search.postprocessing import apply_postprocessors, resolve_postprocessors
from captain_search.providers.base import SearchResponse, SearchResult

WEB_SNIPPET_CHARS: Final[int] = 500
CODE_SNIPPET_CHARS: Final[int] = 800
FETCH_OUTPUT_CHARS: Final[int] = 40000
SECTION_RESULT_LIMIT: Final[int] = 4

_HTML_SNIPPET_HINTS = (
    "<table",
    "<tr",
    "<td",
    "<pre",
    "<span",
    "<mark",
    "<div",
)
_TAG_RE = re.compile(r"<[^>]+>")
_DEEPWIKI_VIEW_RE = re.compile(r"^View this search on DeepWiki:", re.IGNORECASE)
_NAVIGATION_PATTERNS = [
    re.compile(r"^navigation menu$", re.IGNORECASE),
    re.compile(r"^toggle navigation$", re.IGNORECASE),
    re.compile(r"^skip to content$", re.IGNORECASE),
    re.compile(r"^on this page$", re.IGNORECASE),
    re.compile(r"^open main menu$", re.IGNORECASE),
    re.compile(r"^sign in$", re.IGNORECASE),
    re.compile(r"^page source$", re.IGNORECASE),
]


def _normalize_block(text: str) -> str:
    return apply_postprocessors(
        text or "",
        resolve_postprocessors(["normalize_newlines", "collapse_blank_lines", "strip"]),
    )


def truncate_text(text: str, max_chars: int, *, preserve_paragraphs: bool = True) -> str:
    cleaned = _normalize_block(text)
    if len(cleaned) <= max_chars:
        return cleaned

    marker = "\n\n[truncated]"
    cutoff = max_chars - len(marker)
    if cutoff <= 0:
        return marker.strip()

    if preserve_paragraphs:
        split_at = cleaned.rfind("\n\n", 0, cutoff)
        if split_at >= max_chars // 2:
            cutoff = split_at
    else:
        split_at = cleaned.rfind(" ", 0, cutoff)
        if split_at >= max_chars // 2:
            cutoff = split_at

    return f"{cleaned[:cutoff].rstrip()}{marker}"


def clean_result_content(text: str, *, preserve_lines: bool) -> str:
    candidate = html.unescape(text or "")
    lowered = candidate.lower()
    if any(hint in lowered for hint in _HTML_SNIPPET_HINTS):
        candidate = _TAG_RE.sub("", candidate)
    candidate = _normalize_block(candidate)
    return candidate if preserve_lines else re.sub(r"\s+", " ", candidate).strip()


def trim_search_results(
    results: list[SearchResult],
    *,
    max_results: int | None = None,
    max_chars: int,
    preserve_lines: bool,
) -> list[SearchResult]:
    trimmed: list[SearchResult] = []
    for result in results:
        content = truncate_text(
            clean_result_content(result.content, preserve_lines=preserve_lines),
            max_chars,
            preserve_paragraphs=preserve_lines,
        )
        trimmed.append(
            result.model_copy(
                update={
                    "title": result.title.strip(),
                    "url": result.url.strip(),
                    "content": content,
                }
            )
        )
        if max_results is not None and len(trimmed) >= max_results:
            break
    return trimmed


def dedupe_results(results: list[SearchResult], *, max_results: int | None = None) -> list[SearchResult]:
    seen_urls: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        if result.url and result.url in seen_urls:
            continue
        if result.url:
            seen_urls.add(result.url)
        deduped.append(result)
        if max_results is not None and len(deduped) >= max_results:
            break
    return deduped


def format_search_markdown(response: SearchResponse) -> str:
    if response.error:
        return f"**Error:** {response.error}"

    if not response.results:
        return "No results found."

    lines: list[str] = []
    for warning in response.warnings:
        lines.append(f"**Warning:** {warning}")
    if response.warnings:
        lines.append("")

    results = trim_search_results(
        response.results,
        max_chars=WEB_SNIPPET_CHARS,
        preserve_lines=False,
        max_results=None,
    )
    for index, result in enumerate(results, 1):
        lines.append(f"## {index}. {result.title}")
        lines.append(f"**URL:** {result.url}")
        if result.content:
            lines.append("")
            lines.append(result.content)
            lines.append("")
        else:
            lines.append("")
    return "\n".join(lines).strip()


def format_search_json(response: SearchResponse) -> str:
    output = {
        "results": [
            {
                "title": result.title,
                "url": result.url,
                "content": result.content,
            }
            for result in trim_search_results(
                response.results,
                max_chars=WEB_SNIPPET_CHARS,
                preserve_lines=False,
                max_results=None,
            )
        ]
    }
    if response.warnings:
        output["warnings"] = response.warnings
    if response.error:
        output["error"] = response.error
    return json.dumps(output, indent=2)


def prepare_code_results(results: list[SearchResult]) -> list[SearchResult]:
    return trim_search_results(
        dedupe_results(results, max_results=SECTION_RESULT_LIMIT),
        max_chars=CODE_SNIPPET_CHARS,
        preserve_lines=True,
        max_results=SECTION_RESULT_LIMIT,
    )


def format_results_section(title: str, results: list[SearchResult]) -> str:
    cleaned = prepare_code_results(results)
    if not cleaned:
        return ""

    lines = [f"## {title}"]
    for index, result in enumerate(cleaned, 1):
        lines.append(f"### {index}. {result.title}")
        lines.append(f"**URL:** {result.url}")
        if result.content:
            lines.append("")
            lines.append(result.content)
            lines.append("")
        else:
            lines.append("")
    return "\n".join(lines).strip()


def format_error_section(title: str, error: str | None) -> str:
    if not error:
        return ""
    return f"## {title}\n**Error:** {error}"


def format_notes_section(title: str, notes: list[str]) -> str:
    cleaned_notes = [note.strip() for note in notes if note.strip()]
    if not cleaned_notes:
        return ""
    lines = [f"## {title}"]
    lines.extend(f"- {note}" for note in cleaned_notes)
    return "\n".join(lines)


def clean_deepwiki_answer(text: str) -> tuple[str, str | None]:
    cleaned = _normalize_block(text)
    if not cleaned:
        return "", None

    if cleaned.lower().startswith("error processing question:"):
        message = cleaned.split(":", 1)[1].strip() if ":" in cleaned else cleaned
        return "", message

    if cleaned.startswith("Repository not found"):
        return "", cleaned

    lines: list[str] = []
    for raw_line in cleaned.split("\n"):
        stripped = raw_line.strip()
        if stripped == "# Answer":
            continue
        if stripped.lower().startswith("wiki pages you might want to explore:"):
            break
        if _DEEPWIKI_VIEW_RE.match(stripped):
            continue
        lines.append(raw_line)

    answer = truncate_text("\n".join(lines), CODE_SNIPPET_CHARS * 3, preserve_paragraphs=True)
    return answer, None


def clean_fetch_content(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in _normalize_block(text).split("\n"):
        stripped = raw_line.strip()
        if any(pattern.match(stripped) for pattern in _NAVIGATION_PATTERNS):
            continue
        cleaned_lines.append(raw_line)
    return truncate_text("\n".join(cleaned_lines), FETCH_OUTPUT_CHARS, preserve_paragraphs=True)