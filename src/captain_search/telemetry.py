"""Structured JSONL telemetry for Captain Search tool calls."""

from __future__ import annotations

import json
import threading
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

DEFAULT_LOG_DIR = Path.home() / ".captain-search" / "logs"
PAYLOAD_FIELDS = {
    "answer",
    "arguments",
    "content",
    "query",
    "response",
    "result",
    "results",
}

_request_id_var: ContextVar[str | None] = ContextVar("captain_search_request_id", default=None)
_tool_name_var: ContextVar[str | None] = ContextVar("captain_search_tool_name", default=None)
_write_lock = threading.Lock()


@dataclass(slots=True)
class ToolRun:
    """Tool call context for telemetry."""

    request_id: str
    tool_name: str
    started_at: float
    request_token: Token[str | None]
    tool_token: Token[str | None]


def _telemetry_settings() -> tuple[bool, Path, bool]:
    from captain_search.config import get_config

    settings = get_config().settings
    log_dir = Path(settings.captain_search_log_dir or DEFAULT_LOG_DIR).expanduser()
    return (
        settings.captain_search_log_enabled,
        log_dir,
        settings.captain_search_log_full_payloads,
    )


def get_log_file_path() -> Path:
    """Return the active JSONL log file path for the current UTC day."""
    _, log_dir, _ = _telemetry_settings()
    return log_dir / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"


def _serialize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(item) for item in value]
    if isinstance(value, Exception):
        return {"type": type(value).__name__, "message": str(value)}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _summarize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _summarize(value.model_dump(mode="json"))
    if isinstance(value, str):
        return {"length": len(value), "preview": value[:500]}
    if isinstance(value, dict):
        return {
            "keys": list(value.keys()),
            "preview": {str(key): _summarize(item) for key, item in list(value.items())[:5]},
        }
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        return {"count": len(items), "preview": [_summarize(item) for item in items[:3]]}
    return _serialize(value)


def _prepare_field(name: str, value: Any, *, full_payloads: bool) -> Any:
    if full_payloads or name not in PAYLOAD_FIELDS:
        return _serialize(value)
    return _summarize(value)


def _write_record(record: dict[str, Any]) -> None:
    enabled, log_dir, full_payloads = _telemetry_settings()
    if not enabled:
        return

    prepared = {
        key: _prepare_field(key, value, full_payloads=full_payloads)
        for key, value in record.items()
    }
    prepared["timestamp"] = datetime.now(UTC).isoformat()

    log_path = log_dir / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
    line = json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))

    try:
        with _write_lock:
            log_dir.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{line}\n")
    except OSError:
        return


def log_event(event: str, **fields: Any) -> None:
    """Write a telemetry event if logging is enabled."""
    record = {
        "event": event,
        "request_id": fields.pop("request_id", _request_id_var.get()),
        "tool": fields.pop("tool", _tool_name_var.get()),
        **fields,
    }
    _write_record(record)


def start_tool_call(tool_name: str, arguments: dict[str, Any]) -> ToolRun:
    """Create a tool run context and emit a start event."""
    request_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:12]}"
    request_token = _request_id_var.set(request_id)
    tool_token = _tool_name_var.set(tool_name)
    run = ToolRun(
        request_id=request_id,
        tool_name=tool_name,
        started_at=time.monotonic(),
        request_token=request_token,
        tool_token=tool_token,
    )
    log_event("tool_start", arguments=arguments, raw_arguments=arguments)
    return run


def _close_tool_call(run: ToolRun) -> None:
    _request_id_var.reset(run.request_token)
    _tool_name_var.reset(run.tool_token)


def finish_tool_call(
    run: ToolRun,
    *,
    result: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit a successful completion event."""
    log_event(
        "tool_finish",
        elapsed_ms=int((time.monotonic() - run.started_at) * 1000),
        result=result,
        raw_result=result,
        **(metadata or {}),
    )
    _close_tool_call(run)


def fail_tool_call(
    run: ToolRun,
    *,
    error: Exception,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit a failed completion event and clear the current context."""
    log_event(
        "tool_error",
        elapsed_ms=int((time.monotonic() - run.started_at) * 1000),
        error=error,
        **(metadata or {}),
    )
    _close_tool_call(run)