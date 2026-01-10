"""Search tools for MCP server."""

from __future__ import annotations

import asyncio
import json
import random
import time
from enum import Enum

import httpx
from pydantic import BaseModel, ConfigDict, Field

from captain_search.config import Config, get_config
from captain_search.providers import (
    BraveProvider,
    ExaMcpProvider,
    ExaProvider,
    PerplexityProvider,
    SearchProvider,
    SearchResult,
    SerperProvider,
    TavilyProvider,
)
from captain_search.providers.base import SearchResponse


class ResponseFormat(str, Enum):
    """Response format options."""

    MARKDOWN = "markdown"
    JSON = "json"


class SearchInput(BaseModel):
    """Input schema for search_web tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Search query", min_length=1, max_length=500)
    max_results: int = Field(
        default=10, description="Maximum number of results to return", ge=1, le=50
    )
    format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN, description="Response format (markdown or json)"
    )


class MultiSearchInput(BaseModel):
    """Input schema for search_multi tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Search query", min_length=1, max_length=500)
    max_results_per_provider: int = Field(
        default=5, description="Maximum results per provider", ge=1, le=20
    )
    providers: list[str] | None = Field(
        default=None,
        description="Specific providers to use (default: all enabled). Options: serper, brave, tavily, perplexity",
    )
    deduplicate: bool = Field(default=True, description="Remove duplicate URLs from results")
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

    if name == "serper" and api_key:
        return SerperProvider(api_key=api_key, timeout=timeout)
    elif name == "brave" and api_key:
        return BraveProvider(api_key=api_key, timeout=timeout)
    elif name == "tavily" and (api_key or api_keys):
        return TavilyProvider(api_key=api_key, api_keys=api_keys, timeout=timeout)
    elif name == "perplexity" and api_key:
        return PerplexityProvider(api_key=api_key, timeout=timeout)
    elif name == "exa" and (api_key or api_keys):
        # Exa API provider requires API key
        return ExaProvider(api_key=api_key, api_keys=api_keys, timeout=timeout)
    elif name == "exa_mcp":
        # Exa MCP provider works without API key (free endpoint)
        return ExaMcpProvider(timeout=timeout)

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


def _format_results_markdown(response: SearchResponse) -> str:
    """Format search response as markdown - optimized for LLM consumption."""
    if response.error:
        return f"**Error:** {response.error}"

    if not response.results:
        return "No results found."

    lines = []
    for i, result in enumerate(response.results, 1):
        lines.append(f"## {i}. {result.title}")
        lines.append(f"**URL:** {result.url}")
        if result.content:
            # Truncate long content
            content = result.content[:500] + "..." if len(result.content) > 500 else result.content
            lines.append(f"\n{content}\n")
        else:
            lines.append("")

    return "\n".join(lines)


def _format_results_json(response: SearchResponse) -> str:
    """Format search response as JSON - optimized for LLM consumption."""
    # Only include essential fields
    output = {
        "results": [
            {
                "title": r.title,
                "url": r.url,
                "content": r.content,
            }
            for r in response.results
        ]
    }
    # Only include error if present
    if response.error:
        output["error"] = response.error
    return json.dumps(output, indent=2)


async def search_web(
    query: str,
    max_results: int = 10,
    format: str = "markdown",
) -> str:
    """
    Search the web using weighted random provider selection with automatic fallback.

    This tool searches across multiple providers (Serper, Brave, Tavily, Perplexity)
    using weighted random selection based on their free tier limits. If the selected
    provider fails, it automatically tries the next provider in weight order.

    Args:
        query: Search query string
        max_results: Maximum number of results (1-50, default 10)
        format: Response format - "markdown" or "json" (default "markdown")

    Returns:
        Search results in the specified format
    """
    start_time = time.monotonic()
    config = get_config()

    # Get enabled providers and their weights
    weights = config.get_provider_weights()
    if not weights:
        response = SearchResponse(
            query=query,
            error="No search providers configured. Please set API keys in environment variables.",
        )
        return _format_results_markdown(response) if format == "markdown" else _format_results_json(response)

    # Sort providers by weight (descending) for fallback order
    sorted_providers = sorted(weights.keys(), key=lambda x: weights[x], reverse=True)

    # Select initial provider using weighted random
    selected = _weighted_random_choice(weights)

    # Reorder so selected is first, then others in weight order
    providers_to_try = [selected] + [p for p in sorted_providers if p != selected]

    results: list[SearchResult] = []
    providers_used: list[str] = []
    last_error: str | None = None

    for provider_name in providers_to_try:
        provider = _get_provider_instance(provider_name, config)
        if not provider:
            continue

        try:
            results = await provider.search(query, max_results)
            providers_used.append(provider_name)
            last_error = None
            break  # Success!

        except httpx.HTTPStatusError as e:
            last_error = _handle_api_error(e, provider_name)
            continue

        except httpx.TimeoutException:
            last_error = f"{provider_name}: Request timed out"
            continue

        except Exception as e:
            last_error = f"{provider_name}: {type(e).__name__}"
            continue

        finally:
            await provider.close()

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    response = SearchResponse(
        query=query,
        results=results,
        providers_used=providers_used,
        elapsed_ms=elapsed_ms,
        error=last_error if not results else None,
    )

    if format == "json":
        return _format_results_json(response)
    return _format_results_markdown(response)


async def search_multi(
    query: str,
    max_results_per_provider: int = 5,
    providers: list[str] | None = None,
    deduplicate: bool = True,
    format: str = "markdown",
) -> str:
    """
    Search multiple providers in parallel and combine results.

    This tool queries all enabled providers simultaneously, combines the results,
    and optionally deduplicates by URL. Useful for comprehensive searches.

    Args:
        query: Search query string
        max_results_per_provider: Max results from each provider (1-20, default 5)
        providers: Specific providers to use (default: all enabled)
        deduplicate: Remove duplicate URLs (default True)
        format: Response format - "markdown" or "json" (default "markdown")

    Returns:
        Combined search results in the specified format
    """
    config = get_config()

    # Determine which providers to use
    available = config.get_enabled_providers()
    providers_to_use = [p for p in providers if p in available] if providers else available

    if not providers_to_use:
        response = SearchResponse(
            query=query,
            error="No search providers available. Please configure API keys.",
        )
        return _format_results_markdown(response) if format == "markdown" else _format_results_json(response)

    # Create provider instances
    provider_instances = []
    for name in providers_to_use:
        instance = _get_provider_instance(name, config)
        if instance:
            provider_instances.append((name, instance))

    # Search all providers in parallel
    async def search_provider(name: str, provider: SearchProvider) -> tuple[str, list[SearchResult], str | None]:
        try:
            results = await provider.search(query, max_results_per_provider)
            return (name, results, None)
        except httpx.HTTPStatusError as e:
            return (name, [], _handle_api_error(e, name))
        except httpx.TimeoutException:
            return (name, [], f"{name}: Timed out")
        except Exception as e:
            return (name, [], f"{name}: {type(e).__name__}")
        finally:
            await provider.close()

    tasks = [search_provider(name, provider) for name, provider in provider_instances]
    results_by_provider = await asyncio.gather(*tasks)

    # Combine results
    all_results: list[SearchResult] = []
    providers_used: list[str] = []
    errors: list[str] = []

    for name, results, error in results_by_provider:
        if results:
            all_results.extend(results)
            providers_used.append(name)
        if error:
            errors.append(error)

    # Deduplicate by URL
    if deduplicate and all_results:
        seen_urls: set[str] = set()
        unique_results: list[SearchResult] = []
        for result in all_results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                unique_results.append(result)
        all_results = unique_results

    # Build response - optimized for LLM consumption (minimal metadata)
    if format == "json":
        output = {
            "results": [
                {"title": r.title, "url": r.url, "content": r.content}
                for r in all_results
            ]
        }
        if errors and not all_results:
            output["error"] = "; ".join(errors)
        return json.dumps(output, indent=2)

    # Markdown format - clean and focused
    if not all_results:
        if errors:
            return f"**Error:** {'; '.join(errors)}"
        return "No results found."

    lines = []
    for i, result in enumerate(all_results, 1):
        lines.append(f"## {i}. {result.title}")
        lines.append(f"**URL:** {result.url}")
        if result.content:
            content = result.content[:500] + "..." if len(result.content) > 500 else result.content
            lines.append(f"\n{content}\n")
        else:
            lines.append("")

    return "\n".join(lines)


def _handle_api_error(e: httpx.HTTPStatusError, provider: str) -> str:
    """Generate actionable error message for API errors."""
    status = e.response.status_code
    if status == 401:
        return f"{provider}: Invalid API key. Check your {provider.upper()}_API_KEY."
    elif status == 403:
        return f"{provider}: Access forbidden. API key may lack permissions."
    elif status == 429:
        return f"{provider}: Rate limit exceeded. Try again later."
    elif status >= 500:
        return f"{provider}: Server error ({status}). Try again."
    return f"{provider}: HTTP {status}"
