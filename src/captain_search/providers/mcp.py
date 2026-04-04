"""Helpers for parsing MCP SSE responses."""

from __future__ import annotations

import json
from typing import Any


def parse_sse_json_events(payload: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_name: str | None = None
    data_lines: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = None
            return
        data = "\n".join(data_lines).strip()
        data_lines = []
        if not data or data == "ping" or not data.startswith("{"):
            event_name = None
            return
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            event_name = None
            return
        if event_name:
            parsed.setdefault("_event", event_name)
        events.append(parsed)
        event_name = None

    for raw_line in payload.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or None
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    flush()
    return events


def extract_mcp_text_content(payload: str) -> list[str]:
    texts: list[str] = []
    for event in parse_sse_json_events(payload):
        result = event.get("result")
        if not isinstance(result, dict):
            continue

        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            structured_result = structured.get("result")
            if isinstance(structured_result, str) and structured_result.strip():
                texts.append(structured_result.strip())

        content = result.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped