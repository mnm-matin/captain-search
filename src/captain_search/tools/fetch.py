"""Fetch tool for webpage/PDF extraction."""

from __future__ import annotations

import asyncio
import json
import random
from enum import Enum
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from captain_search.config import get_config
from captain_search.health import get_health_registry
from captain_search.postprocessing import apply_postprocessors, resolve_postprocessors
from captain_search.providers.base import FetchResponse
from captain_search.providers.exa import ExaProvider
from captain_search.providers.jina import JinaProvider
from captain_search.providers.parallel import ParallelProvider
from captain_search.providers.tavily import TavilyProvider
from captain_search.rendering import clean_fetch_content
from captain_search.telemetry import fail_tool_call, finish_tool_call, log_event, start_tool_call


class FetchFormat(str, Enum):
    """Output format options for fetch."""

    MARKDOWN = "markdown"
    JSON = "json"
    TEXT = "text"


class FetchInput(BaseModel):
    """Input schema for fetch_webpage tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: str = Field(..., description="URL to fetch content from")
    format: FetchFormat = Field(
        default=FetchFormat.MARKDOWN, description="Output format (markdown or text)"
    )


DEFAULT_FETCH_PROVIDER_WEIGHTS = {
    "parallel": 35,
    "jina": 30,
    "exa": 25,
    "tavily": 10,
}


def _public_fetch_failure_message() -> str:
    return "Failed to fetch the requested URL. Check Captain Search logs for provider-specific errors."


def _collect_fetch_failure_details(
    provider_responses: list[tuple[str, FetchResponse]],
    fallback: FetchResponse,
) -> list[str]:
    details: list[str] = []
    for provider_name, provider_response in provider_responses:
        label = provider_name.capitalize()
        if provider_response.error:
            details.append(f"{label}: {provider_response.error}")
            continue
        if _is_soft_error_response(provider_response):
            reason = _detect_soft_error_reason(provider_response)
            if reason:
                details.append(f"{label}: {reason}")
                continue
        details.append(f"{label}: Empty response")

    if fallback.error:
        details.append(f"Fallback: {fallback.error}")

    return details


def _weighted_random_choice(weights: dict[str, int]) -> str:
    if not weights:
        raise ValueError("No providers available")

    total = sum(weights.values())
    if total == 0:
        return random.choice(list(weights.keys()))

    cutoff = random.uniform(0, total)
    cumulative = 0
    for name, weight in weights.items():
        cumulative += weight
        if cutoff <= cumulative:
            return name

    return next(reversed(weights))


def _provider_weight(provider_name: str, provider_config: object | None) -> int:
    configured = getattr(provider_config, "weight", 0)
    if isinstance(configured, int) and configured > 0:
        return configured
    return DEFAULT_FETCH_PROVIDER_WEIGHTS.get(provider_name, 0)


def _get_fetch_provider_instances(config: object) -> list[tuple[str, object]]:
    providers: list[tuple[str, object]] = []

    parallel_config = getattr(getattr(config, "providers", None), "parallel", None)
    parallel_api_keys = getattr(parallel_config, "api_keys", []) if parallel_config is not None else []
    if (
        parallel_config is not None
        and parallel_config.enabled
        and (parallel_config.api_key or parallel_api_keys)
    ):
        providers.append(
            (
                "parallel",
                ParallelProvider(
                    api_key=parallel_config.api_key,
                    api_keys=parallel_api_keys,
                    timeout=60.0,
                ),
            )
        )

    exa_config = getattr(getattr(config, "providers", None), "exa", None)
    exa_api_keys = getattr(exa_config, "api_keys", []) if exa_config is not None else []
    if exa_config is not None and exa_config.enabled and (exa_config.api_key or exa_api_keys):
        providers.append(
            (
                "exa",
                ExaProvider(
                    api_key=exa_config.api_key,
                    api_keys=exa_api_keys,
                    timeout=60.0,
                ),
            )
        )

    jina_config = getattr(getattr(config, "providers", None), "jina", None)
    jina_api_keys = getattr(jina_config, "api_keys", []) if jina_config is not None else []
    if jina_config is not None and jina_config.enabled:
        providers.append(
            (
                "jina",
                JinaProvider(
                    api_key=jina_config.api_key,
                    api_keys=jina_api_keys,
                    timeout=60.0,
                ),
            )
        )

    tavily_config = getattr(getattr(config, "providers", None), "tavily", None)
    tavily_api_keys = getattr(tavily_config, "api_keys", []) if tavily_config is not None else []
    if (
        tavily_config is not None
        and tavily_config.enabled
        and (tavily_config.api_key or tavily_api_keys)
    ):
        providers.append(
            (
                "tavily",
                TavilyProvider(
                    api_key=tavily_config.api_key,
                    api_keys=tavily_api_keys,
                    timeout=60.0,
                ),
            )
        )

    return providers


def _render_fetch_json(
    *,
    url: str,
    title: str,
    status: int | None,
    content: str,
    error: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "url": url,
        "title": title,
        "status": status,
        "content_length": len(content),
        "content": content,
    }
    if error:
        payload["error"] = error
    return json.dumps(payload, indent=2)


async def fetch_webpage(
    url: str,
    format: str = "markdown",
) -> str:
    """
    Fetch and extract content from a webpage or PDF.

    Uses weighted auto-selection across configured remote extract providers.
    Falls back to other remote providers when the selected one fails or returns junk.
    Falls back to local extraction if all remote providers fail or return empty content.
    For HTML: Trafilatura with recall-friendly settings.
    For PDFs: Local PDF text extraction via pypdf.
    Handles JavaScript-rendered pages and extracts content from PDFs.

    Args:
        url: The URL to fetch (web page or PDF)
        format: Output format - "markdown" or "text" (default "markdown")

    Returns:
        Extracted content in the specified format, or error message

    Examples:
        - Fetch a webpage: fetch_webpage("https://example.com/article")
        - Fetch a PDF: fetch_webpage("https://example.com/document.pdf")
    """
    output_format = (format or "markdown").strip().lower()
    provider_format = "markdown" if output_format == "json" else output_format
    config = get_config()
    source_url = _normalize_source_url(url)
    tool_run = start_tool_call(
        "fetch_webpage",
        {
            "url": url,
            "source_url": source_url,
            "format": output_format,
        },
    )

    def finalize(output: str, **metadata: object) -> str:
        finish_tool_call(tool_run, result=output, metadata=metadata)
        return output

    providers = _get_fetch_provider_instances(config)
    provider_responses: list[tuple[str, FetchResponse]] = []
    provider_weights = {
        provider_name: _provider_weight(
            provider_name,
            getattr(getattr(config, "providers", None), provider_name, None),
        )
        for provider_name, _ in providers
    }
    health_registry = get_health_registry()

    providers_by_name = {provider_name: provider for provider_name, provider in providers}
    closed_weights = {
        provider_name: weight
        for provider_name, weight in provider_weights.items()
        if not health_registry.is_provider_cooling(provider_name)
        and not health_registry.is_provider_recovering(provider_name)
    }
    recovering_weights = {
        provider_name: weight
        for provider_name, weight in provider_weights.items()
        if not health_registry.is_provider_cooling(provider_name)
        and health_registry.is_provider_recovering(provider_name)
    }
    cooling_providers = [
        provider_name for provider_name in provider_weights if health_registry.is_provider_cooling(provider_name)
    ]
    selected_provider_name = (
        _weighted_random_choice(closed_weights or recovering_weights)
        if (closed_weights or recovering_weights)
        else None
    )
    providers_to_try = (
        [(selected_provider_name, providers_by_name[selected_provider_name])]
        + [
            (provider_name, providers_by_name[provider_name])
            for provider_name in [
                *sorted(closed_weights, key=lambda name: provider_weights[name], reverse=True),
                *sorted(recovering_weights, key=lambda name: provider_weights[name], reverse=True),
            ]
            if provider_name != selected_provider_name
        ]
        if selected_provider_name is not None
        else []
    )

    log_event(
        "fetch_provider_selection",
        mode="auto",
        selected_provider=selected_provider_name,
        providers_to_try=[provider_name for provider_name, _ in providers_to_try],
        weights=provider_weights,
        cooling_providers=cooling_providers,
    )

    try:
        used_fallback = False
        selected_provider = ""
        response: FetchResponse | None = None

        for index, (provider_name, provider) in enumerate(providers_to_try):
            request = {
                "url": source_url,
                "format": provider_format,
            }
            log_event(
                "fetch_provider_attempt",
                provider=provider_name,
                requested_url=url,
                source_url=source_url,
                request=request,
            )
            provider_response = await provider.fetch(source_url, format=provider_format)
            provider_responses.append((provider_name, provider_response))
            rejection_reason = None
            if provider_response.error:
                rejection_reason = provider_response.error
            elif not provider_response.content.strip():
                rejection_reason = "empty_content"
            elif _is_soft_error_response(provider_response):
                rejection_reason = _detect_soft_error_reason(provider_response) or "soft_error"
            log_event(
                "fetch_provider_response",
                provider=provider_name,
                requested_url=url,
                source_url=source_url,
                request=request,
                fetched_url=provider_response.url,
                title=provider_response.title,
                content_length=len(provider_response.content),
                error=provider_response.error,
                raw_response=provider_response,
                rejected=rejection_reason is not None,
                rejection_reason=rejection_reason,
            )

            if rejection_reason is not None:
                if index > 0:
                    used_fallback = True
                continue

            response = provider_response
            selected_provider = provider_name
            used_fallback = index > 0
            break

        if response is None:
            if provider_responses:
                last_provider_name, last_response = provider_responses[-1]
                failure_reason = (
                    last_response.error or _detect_soft_error_reason(last_response) or "empty_response"
                )
            else:
                last_provider_name = "none"
                failure_reason = "no_remote_providers_configured"
            log_event(
                "fetch_fallback_start",
                provider=last_provider_name,
                requested_url=url,
                source_url=source_url,
                reason=failure_reason,
            )
            fallback = await _fetch_with_local_fallback(source_url, format=provider_format)
            log_event(
                "fetch_fallback_result",
                requested_url=url,
                source_url=source_url,
                fetched_url=fallback.url,
                title=fallback.title,
                status=fallback.status,
                content_length=len(fallback.content),
                error=fallback.error,
                raw_response=fallback,
            )
            if fallback.error:
                error_details = _collect_fetch_failure_details(provider_responses, fallback)
                public_error = _public_fetch_failure_message()
                if output_format == "json":
                    output = _render_fetch_json(
                        url=source_url,
                        title="",
                        status=fallback.status,
                        content="",
                        error=public_error,
                    )
                else:
                    output = f"**Error:** {public_error}"
                return finalize(
                    output,
                    used_fallback=True,
                    source_url=source_url,
                    public_error=public_error,
                    error_details=error_details,
                    response_format=output_format,
                )
            response = fallback
            used_fallback = True
            selected_provider = "local_fallback"

        postprocessor_names = (
            ["normalize_newlines", "collapse_blank_lines", "strip"]
            if used_fallback
            else ["normalize_newlines", "strip"]
        )
        processors = resolve_postprocessors(postprocessor_names)
        content = apply_postprocessors(response.content, processors)
        content = clean_fetch_content(content) or content.strip()
        title = response.title.strip() if response.title else ""

        # Avoid duplicating title headings (Jina often includes a leading "# Title").
        if title and not content.lstrip().startswith("# "):
            prefix = f"# {title}" if provider_format == "markdown" else title
            content = f"{prefix}\n\n{content}" if content else prefix

        output = content
        status = response.status if response.status is not None else 200
        if output_format == "json":
            output = _render_fetch_json(
                url=response.url,
                title=title,
                status=status,
                content=content,
            )

        return finalize(
            output,
            used_fallback=used_fallback,
            selected_provider=selected_provider,
            final_url=response.url,
            source_url=source_url,
            title=title,
            output_length=len(content),
            response_format=output_format,
            status=status,
        )

    except Exception as error:
        fail_tool_call(
            tool_run,
            error=error,
            metadata={
                "url": url,
                "format": output_format,
            },
        )
        raise

    finally:
        for _, provider in providers:
            await provider.close()


DEFAULT_FALLBACK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _is_pdf_content(url: str, content_type: str, payload: bytes) -> bool:
    if "application/pdf" in (content_type or "").lower():
        return True
    if payload[:4] == b"%PDF":
        return True
    path = urlparse(url).path.lower()
    return path.endswith(".pdf")


def _is_html_content(url: str, content_type: str, payload: bytes) -> bool:
    ct = (content_type or "").lower()
    if "text/html" in ct or "application/xhtml+xml" in ct:
        return True
    path = urlparse(url).path.lower()
    if path.endswith((".html", ".htm", ".xhtml")):
        return True
    sample = payload[:1024].lstrip().lower()
    return sample.startswith(b"<!doctype html") or sample.startswith(b"<html")


def _is_probably_text_content_type(content_type: str) -> bool:
    ct = (content_type or "").lower().split(";", 1)[0].strip()
    if ct.startswith("text/"):
        return True
    return ct in {"application/json", "application/xml", "application/x-yaml"}


def _normalize_source_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc != "github.com":
        return url

    parts = parsed.path.strip("/").split("/")
    if len(parts) < 5 or parts[2] != "blob":
        return url

    owner, repo, _, ref = parts[:4]
    file_path = "/".join(parts[4:])
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{file_path}"


def _detect_soft_error_reason(response: FetchResponse) -> str | None:
    text = f"{response.title}\n{response.content}"
    lowered = text.lower()
    if "secondary rate limit" in lowered or "too many requests" in lowered:
        return "rate_limited"
    if "target url returned error" in lowered:
        return "upstream_http_error"
    if response.title and response.title.lower().startswith("error"):
        return "error_page"
    return None


def _is_soft_error_response(response: FetchResponse) -> bool:
    return _detect_soft_error_reason(response) is not None


async def _download_url(
    url: str,
    timeout_seconds: float = 60.0,
) -> tuple[bytes, str, str, int | None, str | None]:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers=DEFAULT_FALLBACK_HEADERS,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type") or ""
            return resp.content, content_type, str(resp.url), resp.status_code, None
    except httpx.HTTPStatusError as exc:
        return (
            b"",
            "",
            str(exc.response.url) if exc.response is not None else url,
            exc.response.status_code if exc.response is not None else None,
            str(exc),
        )
    except Exception as exc:
        return b"", "", url, None, str(exc)


def _extract_html_with_trafilatura(
    payload: bytes,
    url: str,
    format: str,
) -> tuple[str, str, str | None]:
    import trafilatura

    html = trafilatura.utils.decode_file(payload)
    output_format = "markdown" if format == "markdown" else "txt"

    content = trafilatura.extract(
        html,
        url=url,
        output_format=output_format,
        favor_recall=True,
        include_links=True,
        include_tables=True,
        include_comments=True,
        deduplicate=False,
    )

    if not content:
        # Last resort: extract all text, maximizing recall.
        content = trafilatura.html2txt(html, clean=False)

    if not content:
        return "", "", "Extraction returned empty content"

    metadata = trafilatura.extract_metadata(html, default_url=url)
    title = metadata.title if metadata and getattr(metadata, "title", None) else ""
    return content, title, None


def _extract_pdf_with_pypdf(payload: bytes) -> tuple[str, str, str | None]:
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except Exception as exc:
        return "", "", f"Failed to import pypdf: {exc}"

    try:
        reader = PdfReader(BytesIO(payload), strict=False)
    except Exception as exc:
        return "", "", f"Failed to read PDF: {exc}"

    title = ""
    try:
        meta = reader.metadata
        if meta and getattr(meta, "title", None):
            title = str(meta.title)
    except Exception:
        title = ""

    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        text = text.strip()
        if text:
            pages.append(text)

    content = "\n\n".join(pages).strip()
    if not content:
        return "", title, "Extraction returned empty content"

    return content, title, None


def _extract_bytes_as_text(payload: bytes) -> tuple[str, str | None]:
    try:
        return payload.decode("utf-8"), None
    except UnicodeDecodeError:
        return payload.decode("utf-8", errors="replace"), None


def _extract_with_markitdown(
    payload: bytes,
    *,
    url: str,
    content_type: str,
    format: str,
) -> tuple[str, str, str | None]:
    import importlib.util

    if importlib.util.find_spec("markitdown") is None:
        return "", "", "markitdown is not installed"

    from io import BytesIO
    from pathlib import Path

    from markitdown import MarkItDown, StreamInfo

    extension = Path(urlparse(url).path).suffix
    if extension.startswith("."):
        extension = extension[1:]
    extension = extension or None

    stream_info = StreamInfo(
        mimetype=(content_type or None),
        extension=extension,
        url=url,
    )

    md = MarkItDown(enable_plugins=False)

    try:
        result = md.convert_stream(BytesIO(payload), stream_info=stream_info)
    except Exception as exc:
        return "", "", f"MarkItDown conversion failed: {type(exc).__name__}: {exc}"

    content_md = (result.markdown or "").strip()
    title = (result.title or "").strip()
    if not content_md:
        return "", title, "Conversion returned empty content"

    if format == "text":
        content_text = apply_postprocessors(
            content_md, resolve_postprocessors(["markdown_to_text", "strip"])
        )
        return content_text, title, None

    return content_md, title, None


async def _fetch_with_local_fallback(url: str, format: str) -> FetchResponse:
    import time

    start = time.monotonic()
    payload, content_type, final_url, status_code, download_error = await _download_url(url)
    log_event(
        "fetch_fallback_download",
        requested_url=url,
        final_url=final_url,
        status=status_code,
        content_type=content_type,
        bytes_downloaded=len(payload),
        error=download_error,
    )

    if download_error:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return FetchResponse(
            url=url,
            title="",
            content="",
            format=format,
            status=status_code,
            elapsed_ms=elapsed_ms,
            error=f"Download: {download_error}",
        )

    error = None
    extractor = "markitdown"
    if _is_pdf_content(final_url, content_type, payload):
        extractor = "pypdf"
        content, title, extract_error = await asyncio.to_thread(_extract_pdf_with_pypdf, payload)
        error = f"pypdf: {extract_error}" if extract_error else None
    elif _is_html_content(final_url, content_type, payload):
        extractor = "trafilatura"
        content, title, extract_error = await asyncio.to_thread(
            _extract_html_with_trafilatura, payload, final_url, format
        )
        error = f"Trafilatura: {extract_error}" if extract_error else None
    elif _is_probably_text_content_type(content_type):
        extractor = "text_decode"
        content, decode_error = await asyncio.to_thread(_extract_bytes_as_text, payload)
        title = ""
        error = f"Decode: {decode_error}" if decode_error else None
    else:
        content, title, extract_error = await asyncio.to_thread(
            _extract_with_markitdown,
            payload,
            url=final_url,
            content_type=content_type,
            format=format,
        )
        error = f"MarkItDown: {extract_error}" if extract_error else None

    log_event(
        "fetch_fallback_extract",
        requested_url=url,
        final_url=final_url,
        content_type=content_type,
        extractor=extractor,
        title=title,
        content_length=len(content),
        error=error,
        extracted_content=content,
    )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return FetchResponse(
        url=final_url,
        title=title,
        content=content,
        format=format,
        status=status_code,
        elapsed_ms=elapsed_ms,
        error=error,
    )
