"""Health-aware provider and API key cooldown registry."""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

KEY_BASE_COOLDOWN_SECONDS = 30.0
KEY_MAX_COOLDOWN_SECONDS = 900.0
PROVIDER_BASE_COOLDOWN_SECONDS = 15.0
PROVIDER_MAX_COOLDOWN_SECONDS = 120.0
PROVIDER_FAILURE_THRESHOLD = 2
UNAUTHORIZED_COOLDOWN_SECONDS = 3600.0
HEALTH_STATE_FILENAME = "health.json"


class ProviderCooldownError(RuntimeError):
    """Raised when a provider or all of its API keys are cooling down."""

    def __init__(self, provider: str, retry_after_seconds: int, scope: str):
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds
        self.scope = scope
        super().__init__(
            f"{provider}: Temporarily cooling down for {retry_after_seconds}s ({scope})."
        )


@dataclass(slots=True)
class SlotState:
    """Health state for a provider or API key slot."""

    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_failure_at: float = 0.0
    last_failure_kind: str | None = None
    last_status_code: int | None = None
    last_success_at: float = 0.0
    last_retry_after_seconds: float | None = None


def _utc_iso(timestamp: float) -> str | None:
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    try:
        seconds = float(stripped)
    except ValueError:
        seconds = None

    if seconds is not None:
        return max(0.0, seconds)

    try:
        retry_at = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, retry_at.timestamp() - time.time())


def _cooldown_delay(
    *,
    failures: int,
    base_seconds: float,
    max_seconds: float,
    retry_after_seconds: float | None = None,
) -> float:
    if retry_after_seconds is not None:
        return min(max_seconds, max(1.0, retry_after_seconds))

    exponent = max(0, failures - 1)
    delay = min(max_seconds, base_seconds * (2**exponent))
    return min(max_seconds, delay * random.uniform(0.8, 1.2))


def _api_key_fingerprint(api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return digest[:12]


class HealthRegistry:
    """Persisted health state for provider routing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self._provider_states: dict[str, SlotState] = {}
        self._key_states: dict[str, dict[str, SlotState]] = {}
        self._key_cursors: dict[str, int] = {}

    def _state_path(self) -> Path:
        from captain_search.config import get_config

        log_dir = Path(get_config().settings.captain_search_log_dir).expanduser()
        base_dir = log_dir.parent if log_dir.name == "logs" else log_dir
        return base_dir / HEALTH_STATE_FILENAME

    def _state_from_dict(self, data: dict[str, object]) -> SlotState:
        return SlotState(
            consecutive_failures=int(data.get("consecutive_failures", 0) or 0),
            cooldown_until=float(data.get("cooldown_until", 0.0) or 0.0),
            last_failure_at=float(data.get("last_failure_at", 0.0) or 0.0),
            last_failure_kind=(
                str(data["last_failure_kind"]) if data.get("last_failure_kind") is not None else None
            ),
            last_status_code=(
                int(data["last_status_code"]) if data.get("last_status_code") is not None else None
            ),
            last_success_at=float(data.get("last_success_at", 0.0) or 0.0),
            last_retry_after_seconds=(
                float(data["last_retry_after_seconds"])
                if data.get("last_retry_after_seconds") is not None
                else None
            ),
        )

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        path = self._state_path()
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}

            providers = payload.get("providers", {}) if isinstance(payload, dict) else {}
            if isinstance(providers, dict):
                self._provider_states = {
                    name: self._state_from_dict(state)
                    for name, state in providers.items()
                    if isinstance(state, dict)
                }

            keys = payload.get("keys", {}) if isinstance(payload, dict) else {}
            if isinstance(keys, dict):
                self._key_states = {
                    provider: {
                        fingerprint: self._state_from_dict(state)
                        for fingerprint, state in provider_states.items()
                        if isinstance(state, dict)
                    }
                    for provider, provider_states in keys.items()
                    if isinstance(provider_states, dict)
                }

            cursors = payload.get("key_cursors", {}) if isinstance(payload, dict) else {}
            if isinstance(cursors, dict):
                self._key_cursors = {
                    provider: int(cursor)
                    for provider, cursor in cursors.items()
                    if isinstance(cursor, int | float)
                }

        self._loaded = True

    def _save(self) -> None:
        path = self._state_path()
        payload = {
            "providers": {name: asdict(state) for name, state in self._provider_states.items()},
            "keys": {
                provider: {fingerprint: asdict(state) for fingerprint, state in provider_states.items()}
                for provider, provider_states in self._key_states.items()
            },
            "key_cursors": self._key_cursors,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        except OSError:
            return

    def _provider_state(self, provider: str) -> SlotState:
        return self._provider_states.setdefault(provider, SlotState())

    def _key_state(self, provider: str, fingerprint: str) -> SlotState:
        provider_keys = self._key_states.setdefault(provider, {})
        return provider_keys.setdefault(fingerprint, SlotState())

    def _mark_success(self, state: SlotState, now: float) -> None:
        state.consecutive_failures = 0
        state.cooldown_until = 0.0
        state.last_success_at = now
        state.last_failure_kind = None
        state.last_status_code = None
        state.last_retry_after_seconds = None

    def _mark_failure(
        self,
        state: SlotState,
        *,
        now: float,
        failure_kind: str,
        status_code: int | None,
        retry_after_seconds: float | None,
        base_seconds: float,
        max_seconds: float,
        threshold: int,
    ) -> None:
        state.consecutive_failures += 1
        state.last_failure_at = now
        state.last_failure_kind = failure_kind
        state.last_status_code = status_code
        state.last_retry_after_seconds = retry_after_seconds
        if retry_after_seconds is None and state.consecutive_failures < threshold:
            return
        delay = _cooldown_delay(
            failures=state.consecutive_failures,
            base_seconds=base_seconds,
            max_seconds=max_seconds,
            retry_after_seconds=retry_after_seconds,
        )
        state.cooldown_until = max(state.cooldown_until, now + delay)

    def is_provider_cooling(self, provider: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            return self._provider_state(provider).cooldown_until > time.time()

    def is_provider_recovering(self, provider: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            state = self._provider_state(provider)
            now = time.time()
            return state.consecutive_failures > 0 and state.cooldown_until <= now

    def choose_api_key(
        self,
        provider: str,
        candidates: list[str],
        *,
        error_message: str,
    ) -> str:
        cleaned: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            value = candidate.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            cleaned.append(value)

        if not cleaned:
            raise ValueError(error_message)

        with self._lock:
            self._ensure_loaded()
            now = time.time()
            closed: list[str] = []
            recovering: list[str] = []
            earliest_cooldown: float | None = None

            for candidate in cleaned:
                state = self._key_state(provider, _api_key_fingerprint(candidate))
                if state.cooldown_until > now:
                    earliest_cooldown = state.cooldown_until if earliest_cooldown is None else min(
                        earliest_cooldown,
                        state.cooldown_until,
                    )
                    continue
                if state.consecutive_failures > 0:
                    recovering.append(candidate)
                    continue
                closed.append(candidate)

            selectable = closed or recovering
            if not selectable:
                retry_after = max(1, int((earliest_cooldown or now) - now))
                raise ProviderCooldownError(provider, retry_after, "api_key")

            cursor = self._key_cursors.get(provider, 0)
            selected = selectable[cursor % len(selectable)]
            self._key_cursors[provider] = cursor + 1
            self._save()
            return selected

    def record_success(self, provider: str, *, api_key: str | None = None) -> None:
        with self._lock:
            self._ensure_loaded()
            now = time.time()
            self._mark_success(self._provider_state(provider), now)
            if api_key:
                self._mark_success(self._key_state(provider, _api_key_fingerprint(api_key)), now)
            self._save()

    def record_http_failure(
        self,
        provider: str,
        *,
        status_code: int,
        retry_after: str | None,
        api_key: str | None = None,
    ) -> None:
        with self._lock:
            self._ensure_loaded()
            now = time.time()
            retry_after_seconds = _parse_retry_after(retry_after)

            if status_code in {401, 403} and api_key:
                self._mark_failure(
                    self._key_state(provider, _api_key_fingerprint(api_key)),
                    now=now,
                    failure_kind="unauthorized",
                    status_code=status_code,
                    retry_after_seconds=UNAUTHORIZED_COOLDOWN_SECONDS,
                    base_seconds=UNAUTHORIZED_COOLDOWN_SECONDS,
                    max_seconds=UNAUTHORIZED_COOLDOWN_SECONDS,
                    threshold=1,
                )
            elif status_code == 429 and api_key:
                self._mark_failure(
                    self._key_state(provider, _api_key_fingerprint(api_key)),
                    now=now,
                    failure_kind="rate_limit",
                    status_code=status_code,
                    retry_after_seconds=retry_after_seconds,
                    base_seconds=KEY_BASE_COOLDOWN_SECONDS,
                    max_seconds=KEY_MAX_COOLDOWN_SECONDS,
                    threshold=1,
                )
            else:
                failure_kind = "rate_limit" if status_code == 429 else "server_error"
                self._mark_failure(
                    self._provider_state(provider),
                    now=now,
                    failure_kind=failure_kind,
                    status_code=status_code,
                    retry_after_seconds=retry_after_seconds,
                    base_seconds=PROVIDER_BASE_COOLDOWN_SECONDS,
                    max_seconds=PROVIDER_MAX_COOLDOWN_SECONDS,
                    threshold=1 if retry_after_seconds is not None or status_code == 429 else PROVIDER_FAILURE_THRESHOLD,
                )
            self._save()

    def record_transport_failure(self, provider: str, *, failure_kind: str) -> None:
        with self._lock:
            self._ensure_loaded()
            self._mark_failure(
                self._provider_state(provider),
                now=time.time(),
                failure_kind=failure_kind,
                status_code=None,
                retry_after_seconds=None,
                base_seconds=PROVIDER_BASE_COOLDOWN_SECONDS,
                max_seconds=PROVIDER_MAX_COOLDOWN_SECONDS,
                threshold=PROVIDER_FAILURE_THRESHOLD,
            )
            self._save()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            self._ensure_loaded()
            now = time.time()
            provider_snapshot = {
                provider: {
                    "status": (
                        "cooling"
                        if state.cooldown_until > now
                        else "recovering"
                        if state.consecutive_failures > 0
                        else "healthy"
                    ),
                    "consecutive_failures": state.consecutive_failures,
                    "cooldown_remaining_seconds": max(0.0, state.cooldown_until - now),
                    "cooldown_until": _utc_iso(state.cooldown_until),
                    "last_failure_at": _utc_iso(state.last_failure_at),
                    "last_failure_kind": state.last_failure_kind,
                    "last_status_code": state.last_status_code,
                    "last_success_at": _utc_iso(state.last_success_at),
                    "last_retry_after_seconds": state.last_retry_after_seconds,
                }
                for provider, state in self._provider_states.items()
            }
            key_snapshot = {
                provider: [
                    {
                        "fingerprint": fingerprint,
                        "status": (
                            "cooling"
                            if state.cooldown_until > now
                            else "recovering"
                            if state.consecutive_failures > 0
                            else "healthy"
                        ),
                        "consecutive_failures": state.consecutive_failures,
                        "cooldown_remaining_seconds": max(0.0, state.cooldown_until - now),
                        "cooldown_until": _utc_iso(state.cooldown_until),
                        "last_failure_at": _utc_iso(state.last_failure_at),
                        "last_failure_kind": state.last_failure_kind,
                        "last_status_code": state.last_status_code,
                        "last_success_at": _utc_iso(state.last_success_at),
                        "last_retry_after_seconds": state.last_retry_after_seconds,
                    }
                    for fingerprint, state in sorted(provider_states.items())
                ]
                for provider, provider_states in self._key_states.items()
            }
            return {
                "state_file": str(self._state_path()),
                "providers": provider_snapshot,
                "keys": key_snapshot,
            }


_registry: HealthRegistry | None = None


def get_health_registry() -> HealthRegistry:
    """Return the shared health registry."""
    global _registry
    if _registry is None:
        _registry = HealthRegistry()
    return _registry


def get_health_state_path() -> Path:
    """Return the persisted health state path."""
    return get_health_registry()._state_path()


def reset_health_registry(remove_state: bool = False) -> None:
    """Reset the shared health registry for tests."""
    global _registry
    path = get_health_registry()._state_path() if _registry is not None else HealthRegistry()._state_path()
    _registry = None
    if remove_state:
        try:
            path.unlink()
        except FileNotFoundError:
            return