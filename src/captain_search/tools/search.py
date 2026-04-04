"""Search tools for MCP server."""

from __future__ import annotations

import asyncio
import random
import re
import time
from enum import Enum
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from captain_search.config import Config, get_config
from captain_search.health import ProviderCooldownError, get_health_registry
from captain_search.providers import (
    BraveProvider,
    ExaMcpProvider,
    ExaProvider,
    ParallelProvider,
    PerplexityProvider,
    SearchProvider,
    SearchResult,
    SerperProvider,
    TavilyProvider,
)
from captain_search.providers.base import SearchResponse
from captain_search.rendering import dedupe_results, format_search_json, format_search_markdown
from captain_search.telemetry import fail_tool_call, finish_tool_call, log_event, start_tool_call


class ResponseFormat(str, Enum):
    """Response format options."""

    MARKDOWN = "markdown"
    JSON = "json"


_SITE_FILTER_RE = re.compile(r"site:([^\s]+)", re.IGNORECASE)
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}")
_QUERY_STOPWORDS = {
    "about",
    "docs",
    "guide",
    "guides",
    "official",
    "package",
    "page",
    "pages",
    "results",
    "search",
    "source",
    "using",
    "with",
}
MIN_SEARCH_RESULTS = 1
MAX_SEARCH_RESULTS = 50


class SearchInput(BaseModel):
    """Input schema for search_web tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Search query", min_length=1, max_length=500)
    max_results: int = Field(
        default=10,
        description="Maximum number of results to return",
        ge=MIN_SEARCH_RESULTS,
        le=MAX_SEARCH_RESULTS,
    )
    format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN, description="Response format (markdown or json)"
    )


def _get_provider_instance(name: str, config: Config) -> SearchProvider | None:
    """Create a provider instance from config."""
    provider_config = getattr(config.providers, name, None)
    if not provider_config or not provider_config.enabled:
        return None

    api_key = provider_config.api_key
    api_keys = provider_config.api_keys
    timeout = config.settings.search_timeout_seconds

    if name == "serper" and (api_key or api_keys):
        return SerperProvider(api_key=api_key, api_keys=api_keys, timeout=timeout)
    elif name == "brave" and (api_key or api_keys):
        return BraveProvider(api_key=api_key, api_keys=api_keys, timeout=timeout)
    elif name == "tavily" and (api_key or api_keys):
        return TavilyProvider(api_key=api_key, api_keys=api_keys, timeout=timeout)
    elif name == "perplexity" and (api_key or api_keys):
        return PerplexityProvider(api_key=api_key, api_keys=api_keys, timeout=timeout)
    elif name == "parallel" and (api_key or api_keys):
        return ParallelProvider(api_key=api_key, api_keys=api_keys, timeout=timeout)
    elif name == "exa" and (api_key or api_keys):
        # Exa API provider requires API key
        return ExaProvider(api_key=api_key, api_keys=api_keys, timeout=timeout)
    elif name == "exa_mcp":
        # Exa MCP provider works without API key (free endpoint)
        return ExaMcpProvider(api_key=api_key, api_keys=api_keys, timeout=timeout)

    return None


def _weighted_random_choice(weights: dict[str, int]) -> str:
    """Select a provider based on weights."""
    if not weights:
        raise ValueError("No providers available")

    total = sum(weights.values())
    if total == 0:
        # Equal weights if all are 0
        return random.choice(list(weights.keys()))

    r = random.uniform(0, total)
    cumulative = 0
    for name, weight in weights.items():
        cumulative += weight
        if r <= cumulative:
            return name

    # Fallback to last provider
    return list(weights.keys())[-1]


def _tokenize_query_terms(text: str, *, ignored_terms: set[str] | None = None) -> list[str]:
    ignored = ignored_terms or set()
    seen: set[str] = set()
    terms: list[str] = []
    for raw_token in _QUERY_TOKEN_RE.findall(text.lower()):
        token = raw_token.strip("._-")
        if len(token) < 4 or token in _QUERY_STOPWORDS or token in ignored:
            continue
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def _extract_site_constraints(query: str) -> list[tuple[str, str]]:
    constraints: list[tuple[str, str]] = []
    for raw_constraint in _SITE_FILTER_RE.findall(query):
        token = raw_constraint.strip().rstrip(",.)")
        if not token:
            continue
        if "://" in token:
            parsed = urlparse(token)
            host = parsed.netloc.lower()
            path_prefix = parsed.path.rstrip("/")
        else:
            host, _, path = token.partition("/")
            host = host.lower()
            path_prefix = f"/{path.strip('/')}" if path.strip("/") else ""
        if host.startswith("www."):
            host = host[4:]
        if not host:
            continue
        constraints.append((host, path_prefix))
    return constraints


def _result_matches_site_constraint(result: SearchResult, host: str, path_prefix: str) -> bool:
    parsed = urlparse(result.url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if not (netloc == host or netloc.endswith(f".{host}")):
        return False
    return not path_prefix or parsed.path.lower().startswith(path_prefix.lower())


def _extract_specific_query_terms(query: str) -> list[str]:
    ignored_terms: set[str] = set()
    for host, path_prefix in _extract_site_constraints(query):
        ignored_terms.update(_tokenize_query_terms(host))
        ignored_terms.update(_tokenize_query_terms(path_prefix))

    query_without_sites = _SITE_FILTER_RE.sub(" ", query)
    terms = _tokenize_query_terms(query_without_sites, ignored_terms=ignored_terms)
    specific_terms = [term for term in terms if len(term) >= 8 or any(ch in term for ch in "._-")]
    return specific_terms or terms[:3]


def _result_search_text(result: SearchResult) -> str:
    return " ".join(part for part in (result.title, result.url, result.content) if part).lower()


def _filter_auto_results(
    query: str,
    results: list[SearchResult],
) -> tuple[list[SearchResult], str | None]:
    filtered = list(results)
    if not filtered:
        return [], None

    site_constraints = _extract_site_constraints(query)
    if site_constraints:
        site_matches = [
            result
            for result in filtered
            if any(
                _result_matches_site_constraint(result, host, path_prefix)
                for host, path_prefix in site_constraints
            )
        ]
        if site_matches:
            filtered = site_matches
        else:
            return [], "site_constraint_mismatch"

    specific_terms = _extract_specific_query_terms(query)
    if not specific_terms:
        return filtered, None

    term_matches = [
        result for result in filtered if any(term in _result_search_text(result) for term in specific_terms)
    ]
    if term_matches:
        return term_matches, None

    if site_constraints or len(specific_terms) == 1:
        return [], "specific_term_mismatch"

    return filtered, None


def _format_results_markdown(response: SearchResponse) -> str:
    return format_search_markdown(response)


def _format_results_json(response: SearchResponse) -> str:
    return format_search_json(response)


def _render_search_response(response: SearchResponse, fmt: str) -> str:
    return _format_results_markdown(response) if fmt == "markdown" else _format_results_json(response)


def _validate_max_results(max_results: int) -> str | None:
    if MIN_SEARCH_RESULTS <= max_results <= MAX_SEARCH_RESULTS:
        return None
    return f"max_results must be between {MIN_SEARCH_RESULTS} and {MAX_SEARCH_RESULTS}."


def _public_provider_failure_message(mode: str, *, unknown: list[str] | None = None) -> str:
    if mode == "explicit":
        message = (
            "Search failed for the requested providers. "
            "Check Captain Search logs for provider-specific errors."
        )
    else:
        message = (
            "Search failed across configured providers. "
            "Check Captain Search logs for provider-specific errors."
        )

    if unknown:
        return f"Unknown provider(s): {', '.join(unknown)}. {message}"
    return message


def _record_provider_success(provider: object) -> None:
    recorder = getattr(provider, "record_success", None)
    if callable(recorder):
        recorder()


def _record_provider_http_error(provider: object, error: httpx.HTTPStatusError) -> None:
    recorder = getattr(provider, "record_http_error", None)
    if callable(recorder):
        recorder(error)


def _record_provider_transport_error(provider: object, error: Exception) -> None:
    recorder = getattr(provider, "record_transport_error", None)
    if callable(recorder):
        recorder(error)


async def search_web(
    query: str,
    max_results: int = 10,
    format: str = "markdown",
    provider: str | None = None,
) -> str:
    """
    Search the web using weighted random provider selection with automatic fallback.

    This tool searches across multiple providers (Serper, Brave, Tavily, Perplexity, Parallel)
    using weighted random selection based on their free tier limits. If the selected
    provider fails, it automatically tries the next provider in weight order.

    Args:
        query: Search query string
        max_results: Maximum number of results (1-50, default 10)
        format: Response format - "markdown" or "json" (default "markdown")
        provider: Provider selector - "auto" (default), "multi"/"all", provider name,
            or comma-separated provider list

    Returns:
        Search results in the specified format
    """
    start_time = time.monotonic()
    fmt = (format or "markdown").strip().lower()
    provider_value = (provider or "auto").strip().lower()
    config = get_config()
    health_registry = get_health_registry()
    tool_run = start_tool_call(
        "search_web",
        {
            "query": query,
            "max_results": max_results,
            "format": fmt,
            "provider": provider_value,
        },
    )

    def finalize(output: str, **metadata: object) -> str:
        finish_tool_call(tool_run, result=output, metadata=metadata)
        return output

    try:
        validation_error = _validate_max_results(max_results)
        if validation_error is not None:
            response = SearchResponse(query=query, error=validation_error)
            output = _render_search_response(response, fmt)
            return finalize(
                output,
                mode="validation_error",
                response_format=fmt,
                error=validation_error,
            )

        known_providers = {"serper", "brave", "tavily", "perplexity", "parallel", "exa", "exa_mcp"}

        async def run_explicit_providers(
            requested: list[str], unknown: list[str]
        ) -> str:
            provider_instances: list[tuple[str, SearchProvider]] = []
            for name in requested:
                instance = _get_provider_instance(name, config)
                if instance is not None:
                    provider_instances.append((name, instance))

            if not provider_instances:
                base_error = (
                    "No search providers configured. Please set API keys in environment variables."
                )
                if unknown and requested:
                    base_error = (
                        f"Unknown provider(s): {', '.join(unknown)}. "
                        f"{base_error}"
                    )
                elif unknown and not requested:
                    base_error = f"Unknown provider(s): {', '.join(unknown)}"

                response = SearchResponse(query=query, error=base_error)
                return _render_search_response(response, fmt)

            async def search_provider(
                name: str, provider_instance: SearchProvider
            ) -> tuple[str, list[SearchResult], str | None]:
                request = {
                    "query": query,
                    "max_results": max_results,
                }
                if health_registry.is_provider_cooling(name):
                    error = f"{name}: Temporarily cooling down. Try again later."
                    log_event(
                        "provider_result",
                        provider=name,
                        mode="explicit",
                        request=request,
                        results=[],
                        raw_results=[],
                        result_count=0,
                        error=error,
                    )
                    return name, [], error

                log_event(
                    "provider_attempt",
                    provider=name,
                    mode="explicit",
                    query=query,
                    max_results=max_results,
                    request=request,
                )
                try:
                    results = await provider_instance.search(query, max_results)
                    _record_provider_success(provider_instance)
                    log_event(
                        "provider_result",
                        provider=name,
                        mode="explicit",
                        request=request,
                        results=results,
                        raw_results=results,
                        result_count=len(results),
                        error=None,
                    )
                    return name, results, None
                except ProviderCooldownError as e:
                    error = str(e)
                    log_event(
                        "provider_result",
                        provider=name,
                        mode="explicit",
                        request=request,
                        results=[],
                        raw_results=[],
                        result_count=0,
                        error=error,
                    )
                    return name, [], error
                except httpx.HTTPStatusError as e:
                    _record_provider_http_error(provider_instance, e)
                    error = _handle_api_error(e, name)
                    log_event(
                        "provider_result",
                        provider=name,
                        mode="explicit",
                        request=request,
                        results=[],
                        raw_results=[],
                        result_count=0,
                        error=error,
                    )
                    return name, [], error
                except httpx.TimeoutException as e:
                    _record_provider_transport_error(provider_instance, e)
                    error = f"{name}: Request timed out"
                    log_event(
                        "provider_result",
                        provider=name,
                        mode="explicit",
                        request=request,
                        results=[],
                        raw_results=[],
                        result_count=0,
                        error=error,
                    )
                    return name, [], error
                except Exception as e:
                    _record_provider_transport_error(provider_instance, e)
                    detail = str(e).strip()
                    error = f"{name}: {type(e).__name__}: {detail}" if detail else f"{name}: {type(e).__name__}"
                    log_event(
                        "provider_result",
                        provider=name,
                        mode="explicit",
                        request=request,
                        results=[],
                        raw_results=[],
                        result_count=0,
                        error=error,
                    )
                    return name, [], error
                finally:
                    await provider_instance.close()

            tasks = [
                search_provider(name, provider_instance)
                for name, provider_instance in provider_instances
            ]
            results_by_provider = await asyncio.gather(*tasks)

            all_results: list[SearchResult] = []
            providers_used: list[str] = []
            errors: list[str] = []

            for name, results, error in results_by_provider:
                if results:
                    all_results.extend(results)
                    providers_used.append(name)
                if error:
                    errors.append(error)

            combined_count = len(all_results)
            if all_results:
                all_results = dedupe_results(all_results, max_results=max_results)
                log_event(
                    "provider_merge",
                    mode="explicit",
                    requested_providers=requested,
                    combined_result_count=combined_count,
                    deduped_result_count=len(all_results),
                    final_result_count=len(all_results),
                    max_results=max_results,
                )

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            error: str | None = None
            warnings: list[str] = []
            if not all_results:
                if errors:
                    error = _public_provider_failure_message("explicit", unknown=unknown)
                elif unknown:
                    error = f"Unknown provider(s): {', '.join(unknown)}"
            elif unknown:
                warnings.append(f"Ignored unknown provider(s): {', '.join(unknown)}")

            response = SearchResponse(
                query=query,
                results=all_results,
                providers_used=providers_used,
                elapsed_ms=elapsed_ms,
                warnings=warnings,
                error=error,
            )
            return _render_search_response(response, fmt)

        # Explicit provider modes
        if provider_value in {"multi", "all"}:
            requested = config.get_enabled_providers()
            output = await run_explicit_providers(requested=requested, unknown=[])
            return finalize(
                output,
                mode="multi",
                requested_providers=requested,
                response_format=fmt,
            )

        if provider_value not in {"", "auto"}:
            raw_names = [name.strip().lower() for name in provider_value.split(",") if name.strip()]
            if not raw_names:
                provider_value = "auto"
            else:
                requested: list[str] = []
                unknown: list[str] = []
                seen: set[str] = set()
                for name in raw_names:
                    if name in seen:
                        continue
                    seen.add(name)
                    if name in known_providers:
                        requested.append(name)
                    else:
                        unknown.append(name)
                output = await run_explicit_providers(requested=requested, unknown=unknown)
                return finalize(
                    output,
                    mode="explicit",
                    requested_providers=requested,
                    unknown_providers=unknown,
                    response_format=fmt,
                )

        # Auto mode: weighted single-provider selection with fallback

        weights = config.get_provider_weights()
        if not weights:
            response = SearchResponse(
                query=query,
                error="No search providers configured. Please set API keys in environment variables.",
            )
            output = _render_search_response(response, fmt)
            return finalize(output, mode="auto", response_format=fmt, error=response.error)

        closed_weights = {
            name: weight
            for name, weight in weights.items()
            if not health_registry.is_provider_cooling(name) and not health_registry.is_provider_recovering(name)
        }
        recovering_weights = {
            name: weight
            for name, weight in weights.items()
            if not health_registry.is_provider_cooling(name) and health_registry.is_provider_recovering(name)
        }
        cooling_providers = [name for name in weights if health_registry.is_provider_cooling(name)]

        candidate_weights = closed_weights or recovering_weights
        if not candidate_weights:
            response = SearchResponse(
                query=query,
                error="All configured providers are temporarily cooling down. Try again later.",
            )
            output = _render_search_response(response, fmt)
            return finalize(
                output,
                mode="auto",
                response_format=fmt,
                cooling_providers=cooling_providers,
                error=response.error,
            )

        closed_sorted = sorted(closed_weights.keys(), key=lambda x: weights[x], reverse=True)
        recovering_sorted = sorted(recovering_weights.keys(), key=lambda x: weights[x], reverse=True)
        selected = _weighted_random_choice(candidate_weights)
        providers_to_try = [selected] + [
            provider_name
            for provider_name in [*closed_sorted, *recovering_sorted]
            if provider_name != selected
        ]
        log_event(
            "provider_selection",
            mode="auto",
            selected_provider=selected,
            providers_to_try=providers_to_try,
            weights=weights,
            cooling_providers=cooling_providers,
        )

        results: list[SearchResult] = []
        providers_used: list[str] = []
        last_error: str | None = None
        rejected_for_quality = False
        had_provider_errors = False
        had_cooldown_errors = False

        for provider_name in providers_to_try:
            provider = _get_provider_instance(provider_name, config)
            if not provider:
                log_event(
                    "provider_skipped",
                    provider=provider_name,
                    mode="auto",
                    reason="not_configured",
                )
                continue

            request = {
                "query": query,
                "max_results": max_results,
            }
            log_event(
                "provider_attempt",
                provider=provider_name,
                mode="auto",
                query=query,
                max_results=max_results,
                request=request,
            )
            try:
                raw_results = await provider.search(query, max_results)
                _record_provider_success(provider)
                deduped_results = dedupe_results(raw_results, max_results=max_results)
                filtered_results, rejection_reason = _filter_auto_results(query, deduped_results)
                if not filtered_results:
                    log_event(
                        "provider_result",
                        provider=provider_name,
                        mode="auto",
                        request=request,
                        results=[],
                        raw_results=raw_results,
                        deduped_results=deduped_results,
                        filtered_results=filtered_results,
                        raw_result_count=len(raw_results),
                        result_count=0,
                        error=None,
                        rejection_reason=rejection_reason,
                    )
                    if rejection_reason is not None:
                        rejected_for_quality = True
                        log_event(
                            "provider_rejected",
                            provider=provider_name,
                            mode="auto",
                            query=query,
                            reason=rejection_reason,
                            raw_result_count=len(raw_results),
                            deduped_result_count=len(deduped_results),
                        )
                    continue

                results = filtered_results
                providers_used.append(provider_name)
                last_error = None
                log_event(
                    "provider_result",
                    provider=provider_name,
                    mode="auto",
                    request=request,
                    results=results,
                    raw_results=raw_results,
                    deduped_results=deduped_results,
                    filtered_results=filtered_results,
                    raw_result_count=len(raw_results),
                    result_count=len(results),
                    error=None,
                )
                break

            except ProviderCooldownError as e:
                had_cooldown_errors = True
                last_error = str(e)
                log_event(
                    "provider_result",
                    provider=provider_name,
                    mode="auto",
                    request=request,
                    results=[],
                    raw_results=[],
                    result_count=0,
                    error=last_error,
                )
                continue

            except httpx.HTTPStatusError as e:
                had_provider_errors = True
                _record_provider_http_error(provider, e)
                last_error = _handle_api_error(e, provider_name)
                log_event(
                    "provider_result",
                    provider=provider_name,
                    mode="auto",
                    request=request,
                    results=[],
                    raw_results=[],
                    result_count=0,
                    error=last_error,
                )
                continue

            except httpx.TimeoutException as e:
                had_provider_errors = True
                _record_provider_transport_error(provider, e)
                last_error = f"{provider_name}: Request timed out"
                log_event(
                    "provider_result",
                    provider=provider_name,
                    mode="auto",
                    request=request,
                    results=[],
                    raw_results=[],
                    result_count=0,
                    error=last_error,
                )
                continue

            except Exception as e:
                had_provider_errors = True
                _record_provider_transport_error(provider, e)
                detail = str(e).strip()
                last_error = (
                    f"{provider_name}: {type(e).__name__}: {detail}"
                    if detail
                    else f"{provider_name}: {type(e).__name__}"
                )
                log_event(
                    "provider_result",
                    provider=provider_name,
                    mode="auto",
                    request=request,
                    results=[],
                    raw_results=[],
                    result_count=0,
                    error=last_error,
                )
                continue

            finally:
                await provider.close()

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if not providers_used and last_error is None and not rejected_for_quality:
            last_error = "All configured providers failed. Try again later."

        public_error: str | None = None
        if not providers_used:
            if had_provider_errors:
                public_error = _public_provider_failure_message("auto")
            elif had_cooldown_errors:
                public_error = "All configured providers are temporarily cooling down. Try again later."
            elif last_error:
                public_error = last_error

        response = SearchResponse(
            query=query,
            results=results,
            providers_used=providers_used,
            elapsed_ms=elapsed_ms,
            error=public_error,
        )
        output = _render_search_response(response, fmt)
        return finalize(
            output,
            mode="auto",
            selected_provider=selected,
            providers_tried=providers_to_try,
            providers_used=providers_used,
            response_format=fmt,
        )
    except Exception as error:
        fail_tool_call(
            tool_run,
            error=error,
            metadata={
                "provider": provider_value,
                "response_format": fmt,
            },
        )
        raise


def _handle_api_error(e: httpx.HTTPStatusError, provider: str) -> str:
    """Generate actionable error message for API errors."""
    status = e.response.status_code
    if status == 401:
        return (
            f"{provider}: Invalid API key. "
            f"Check your {provider.upper()}_API_KEY or {provider.upper()}_API_KEYS."
        )
    elif status == 403:
        return f"{provider}: Access forbidden. API key may lack permissions."
    elif status == 429:
        return f"{provider}: Rate limit exceeded. Try again later."
    elif status >= 500:
        return f"{provider}: Server error ({status}). Try again."
    return f"{provider}: HTTP {status}"
