"""Tools for search-proxy."""

from captain_search.tools.fetch import search_fetch_webpage
from captain_search.tools.search import search_multi, search_web

__all__ = [
    "search_web",
    "search_multi",
    "search_fetch_webpage",
]
