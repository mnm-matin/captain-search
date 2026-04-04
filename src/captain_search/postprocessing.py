"""Content post-processing utilities.

These helpers provide a small, composable pipeline for normalizing and cleaning
extracted content (from providers or local fallbacks).

Postprocessors are intentionally simple callables to make it easy to add/compose
new steps (e.g., future de-duplication or compression passes).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

PostProcessor = Callable[[str], str]


def normalize_newlines(text: str) -> str:
    if not text:
        return text
    return text.replace("\r\n", "\n").replace("\r", "\n")


_COLLAPSE_BLANK_LINES_RE = re.compile(r"\n{3,}")


def collapse_blank_lines(text: str) -> str:
    if not text:
        return text
    text = normalize_newlines(text)
    return _COLLAPSE_BLANK_LINES_RE.sub("\n\n", text)


def strip_surrounding_whitespace(text: str) -> str:
    return text.strip()


_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def markdown_to_text(text: str) -> str:
    """Best-effort Markdown → plain text.

    This is intentionally conservative (no external deps). It's meant as a fallback
    when we can only extract Markdown but the caller requested plain text.
    """

    if not text:
        return text

    text = normalize_newlines(text)

    # Remove fenced-code markers but keep code contents.
    lines: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        lines.append(line)

    text = "\n".join(lines)

    # Inline code.
    text = text.replace("`", "")

    # Headings.
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)

    # Links: [text](url) -> text (url)
    text = _MARKDOWN_LINK_RE.sub(r"\1 (\2)", text)

    # Images: ![alt](url) -> alt (url)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1 (\2)", text)

    # Emphasis markers.
    text = text.replace("**", "").replace("*", "").replace("__", "").replace("_", "")

    return text


POSTPROCESSOR_REGISTRY: dict[str, PostProcessor] = {
    "normalize_newlines": normalize_newlines,
    "collapse_blank_lines": collapse_blank_lines,
    "strip": strip_surrounding_whitespace,
    "markdown_to_text": markdown_to_text,
}


def resolve_postprocessors(names: Sequence[str]) -> list[PostProcessor]:
    processors: list[PostProcessor] = []
    for name in names:
        processor = POSTPROCESSOR_REGISTRY.get(name)
        if processor is None:
            raise ValueError(f"Unknown postprocessor: {name}")
        processors.append(processor)
    return processors


def apply_postprocessors(text: str, processors: Sequence[PostProcessor]) -> str:
    for processor in processors:
        text = processor(text)
    return text
