"""Tests for search-proxy."""


def test_imports():
    """Test that all modules can be imported."""
    from captain_search import __version__
    from captain_search.config import Config, get_config  # noqa: F401
    from captain_search.providers import (
        BraveProvider,  # noqa: F401
        JinaProvider,  # noqa: F401
        PerplexityProvider,  # noqa: F401
        SearchProvider,  # noqa: F401
        SearchResult,  # noqa: F401
        SerperProvider,  # noqa: F401
        TavilyProvider,  # noqa: F401
    )
    from captain_search.tools import (  # noqa: F401
        search_fetch_webpage,
        search_multi,
        search_web,
    )

    assert __version__ == "0.1.0"


def test_config_defaults():
    """Test default configuration values."""
    from captain_search.config import Config, reset_config

    reset_config()
    config = Config()

    # Default weights
    assert config.providers.serper.weight == 42
    assert config.providers.brave.weight == 33
    assert config.providers.tavily.weight == 17
    assert config.providers.perplexity.weight == 8

    # All enabled by default
    assert config.providers.serper.enabled is True
    assert config.providers.brave.enabled is True
    assert config.providers.tavily.enabled is True
    assert config.providers.perplexity.enabled is True


def test_search_result_model():
    """Test SearchResult model."""
    from captain_search.providers.base import SearchResult

    result = SearchResult(
        title="Test Title",
        url="https://example.com",
        content="Test content",
        source="test",
    )

    assert result.title == "Test Title"
    assert result.url == "https://example.com"
    assert result.content == "Test content"
    assert result.source == "test"


def test_weighted_random_choice():
    """Test weighted random selection."""
    from captain_search.tools.search import _weighted_random_choice

    weights = {"a": 90, "b": 10}

    # Run many times and check distribution
    counts = {"a": 0, "b": 0}
    for _ in range(1000):
        choice = _weighted_random_choice(weights)
        counts[choice] += 1

    # Should be roughly 90/10 distribution
    assert counts["a"] > 700  # Should be around 900
    assert counts["b"] < 300  # Should be around 100
