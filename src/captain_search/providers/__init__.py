"""Search providers for search-proxy."""

from captain_search.providers.base import SearchProvider, SearchResult
from captain_search.providers.brave import BraveProvider
from captain_search.providers.exa import ExaProvider
from captain_search.providers.exa_mcp import ExaMcpProvider
from captain_search.providers.jina import JinaProvider
from captain_search.providers.perplexity import PerplexityProvider
from captain_search.providers.serper import SerperProvider
from captain_search.providers.tavily import TavilyProvider

__all__ = [
    "SearchProvider",
    "SearchResult",
    "SerperProvider",
    "BraveProvider",
    "TavilyProvider",
    "PerplexityProvider",
    "JinaProvider",
    "ExaProvider",
    "ExaMcpProvider",
]
