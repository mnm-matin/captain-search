"""Search Proxy - A unified search API with MCP support."""

from importlib.metadata import PackageNotFoundError, version

try:
	__version__ = version("captain-search")
except PackageNotFoundError:
	__version__ = "0.0.0"
