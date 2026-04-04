"""Diagnostic reporting for Captain Search provider health."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from captain_search.config import get_config
from captain_search.health import get_health_registry
from captain_search.providers.github_code_search import get_gh_cli_auth_state

DOCTOR_WINDOW_HOURS = 24


def _format_seconds(value: float) -> str:
    seconds = int(max(0, round(value)))
    minutes, remaining_seconds = divmod(seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {remaining_minutes}m"
    if minutes:
        return f"{minutes}m {remaining_seconds}s"
    return f"{remaining_seconds}s"


def _recent_provider_stats(log_dir: Path) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    if not log_dir.exists():
        return stats

    cutoff = datetime.now(UTC) - timedelta(hours=DOCTOR_WINDOW_HOURS)
    for path in sorted(log_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        for line in lines:
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            timestamp_raw = event.get("timestamp")
            if not isinstance(timestamp_raw, str):
                continue
            try:
                timestamp = datetime.fromisoformat(timestamp_raw)
            except ValueError:
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            if timestamp < cutoff:
                continue

            provider = event.get("provider")
            if not isinstance(provider, str):
                continue

            item = stats.setdefault(
                provider,
                {
                    "requests": 0,
                    "successes": 0,
                    "errors": 0,
                    "rate_limits": 0,
                    "empty": 0,
                },
            )

            if event.get("event") == "provider_result":
                item["requests"] += 1
                error = event.get("error")
                result_count = event.get("result_count")
                if isinstance(error, str) and error:
                    item["errors"] += 1
                    if "rate limit" in error.lower():
                        item["rate_limits"] += 1
                elif isinstance(result_count, int) and result_count > 0:
                    item["successes"] += 1
                else:
                    item["empty"] += 1

            if event.get("event") == "fetch_provider_response":
                item["requests"] += 1
                error = event.get("error")
                content_length = event.get("content_length")
                if isinstance(error, str) and error:
                    item["errors"] += 1
                    if "rate limit" in error.lower():
                        item["rate_limits"] += 1
                elif isinstance(content_length, int) and content_length > 0:
                    item["successes"] += 1
                else:
                    item["empty"] += 1

    return stats


def _provider_keys(provider_config: object | None) -> list[str]:
    if provider_config is None:
        return []
    api_key = getattr(provider_config, "api_key", None)
    api_keys = getattr(provider_config, "api_keys", []) or []
    keys: list[str] = []
    seen: set[str] = set()
    for value in [api_key, *api_keys]:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        keys.append(cleaned)
    return keys


def _recent_summary(stats: dict[str, dict[str, int]], provider_name: str) -> str:
    recent = stats.get(provider_name, {})
    return (
        f"{recent.get('successes', 0)} ok / "
        f"{recent.get('errors', 0)} err / "
        f"{recent.get('rate_limits', 0)} rl"
    )


def doctor_report() -> str:
    """Render a markdown doctor report for provider configuration and health."""
    config = get_config()
    snapshot = get_health_registry().snapshot()
    log_dir = Path(config.settings.captain_search_log_dir).expanduser()
    stats = _recent_provider_stats(log_dir)
    provider_configs = config.providers.model_dump()

    lines = [
        "# Captain Search Doctor",
        "",
        f"State file: {snapshot['state_file']}",
        f"Recent telemetry window: last {DOCTOR_WINDOW_HOURS}h",
        "",
        "## Providers",
        "",
        "| Provider | Enabled | Keys | Status | Cooldown | Recent |",
        "|---|---|---|---|---|---|",
    ]

    for provider_name in provider_configs:
        provider_config = getattr(config.providers, provider_name)
        keys = _provider_keys(provider_config)
        provider_state = snapshot["providers"].get(provider_name, {})
        provider_status = provider_state.get("status", "healthy")
        enabled = bool(getattr(provider_config, "enabled", False))
        cooldown = provider_state.get("cooldown_remaining_seconds", 0.0) or 0.0
        recent_summary = _recent_summary(stats, provider_name)

        if not enabled:
            status = "disabled"
        elif provider_name == "jina" and not keys:
            status = "unauthenticated"
        elif provider_name != "exa_mcp" and not keys:
            status = "no_key"
        else:
            status = provider_status

        lines.append(
            "| {provider} | {enabled} | {keys} | {status} | {cooldown} | {recent} |".format(
                provider=provider_name,
                enabled="yes" if enabled else "no",
                keys=len(keys),
                status=status,
                cooldown=_format_seconds(cooldown) if cooldown else "-",
                recent=recent_summary,
            )
        )

    gh_installed, gh_authenticated = get_gh_cli_auth_state()
    github_provider_name = "github_code_search"
    github_provider_state = snapshot["providers"].get(github_provider_name, {})
    github_cooldown = github_provider_state.get("cooldown_remaining_seconds", 0.0) or 0.0
    if not gh_installed:
        github_enabled = "no"
        github_keys = 0
        github_status = "unavailable"
    elif not gh_authenticated:
        github_enabled = "yes"
        github_keys = 0
        github_status = "unauthenticated"
    else:
        github_enabled = "yes"
        github_keys = 1
        github_status = github_provider_state.get("status", "healthy")

    lines.append(
        "| {provider} | {enabled} | {keys} | {status} | {cooldown} | {recent} |".format(
            provider=github_provider_name,
            enabled=github_enabled,
            keys=github_keys,
            status=github_status,
            cooldown=_format_seconds(github_cooldown) if github_cooldown else "-",
            recent=_recent_summary(stats, github_provider_name),
        )
    )

    cooling_keys = [
        (provider_name, item)
        for provider_name, items in snapshot["keys"].items()
        for item in items
        if item["status"] in {"cooling", "recovering"}
    ]
    if cooling_keys:
        lines.extend(
            [
                "",
                "## Key Cooldowns",
                "",
                "| Provider | Key | Status | Cooldown | Last Failure |",
                "|---|---|---|---|---|",
            ]
        )
        for provider_name, item in cooling_keys:
            lines.append(
                "| {provider} | {key} | {status} | {cooldown} | {failure} |".format(
                    provider=provider_name,
                    key=item["fingerprint"],
                    status=item["status"],
                    cooldown=_format_seconds(item["cooldown_remaining_seconds"]),
                    failure=item["last_failure_kind"] or "-",
                )
            )

    if not stats:
        lines.extend(["", "No recent telemetry found."])

    return "\n".join(lines)