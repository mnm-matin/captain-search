"""Tools for search-proxy."""

from captain_search.tools.code_search import search_code
from captain_search.tools.fetch import fetch_webpage
from captain_search.tools.search import search_web

__all__ = [
    "search_code",
    "search_web",
    "fetch_webpage",
]
