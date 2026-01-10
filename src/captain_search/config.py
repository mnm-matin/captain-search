"""Configuration management for search-proxy."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings


class ProviderConfig(BaseModel):
    """Configuration for a single search provider."""

    model_config = ConfigDict(extra="forbid")

    weight: int = Field(default=0, ge=0, le=100, description="Selection weight (0-100)")
    enabled: bool = Field(default=True, description="Whether provider is enabled")
    api_key: str | None = Field(default=None, description="API key (can be set via env var)")
    api_keys: list[str] = Field(default_factory=list, description="Multiple API keys for rotation")


class ProvidersConfig(BaseModel):
    """Configuration for all providers."""

    model_config = ConfigDict(extra="forbid")

    serper: ProviderConfig = Field(default_factory=lambda: ProviderConfig(weight=42))
    brave: ProviderConfig = Field(default_factory=lambda: ProviderConfig(weight=33))
    tavily: ProviderConfig = Field(default_factory=lambda: ProviderConfig(weight=17))
    perplexity: ProviderConfig = Field(default_factory=lambda: ProviderConfig(weight=8))
    jina: ProviderConfig = Field(default_factory=lambda: ProviderConfig(weight=0, enabled=True))
    exa: ProviderConfig = Field(default_factory=lambda: ProviderConfig(weight=0, enabled=False))  # Requires API key
    exa_mcp: ProviderConfig = Field(default_factory=lambda: ProviderConfig(weight=15, enabled=True))  # Free, no key needed


class Settings(BaseSettings):
    """Global settings loaded from environment variables."""

    model_config = ConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Keys from environment
    serper_api_key: str | None = Field(default=None, alias="SERPER_API_KEY")
    brave_api_key: str | None = Field(default=None, alias="BRAVE_API_KEY")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    tavily_api_key_2: str | None = Field(default=None, alias="TAVILY_API_KEY_2")
    perplexity_api_key: str | None = Field(default=None, alias="PERPLEXITY_API_KEY")
    jina_api_key: str | None = Field(default=None, alias="JINA_API_KEY")
    exa_api_key: str | None = Field(default=None, alias="EXA_API_KEY")

    # Timeouts
    search_timeout_seconds: float = Field(default=30.0, alias="SEARCH_TIMEOUT_SECONDS")

    # Server settings
    mcp_server_name: str = Field(default="search_mcp", alias="MCP_SERVER_NAME")
    mcp_server_port: int = Field(default=8000, alias="MCP_SERVER_PORT")
    mcp_auth_token: str | None = Field(
        default=None,
        alias="MCP_AUTH_TOKEN",
        description=(
            "Optional bearer token to protect the remote MCP endpoint. "
            "If unset/empty, the server runs without authentication. "
            "Clients should send: Authorization: Bearer <token>."
        ),
    )


# Default weights based on free tier limits:
# - Serper: 2500/month → 42%
# - Brave: 2000/month → 33%
# - Tavily: 1000-2000/month → 17%
# - Perplexity: ~500/month → 8%
DEFAULT_WEIGHTS = {
    "serper": 42,
    "brave": 33,
    "tavily": 17,
    "perplexity": 8,
}


class Config:
    """Main configuration class combining settings and provider config."""

    def __init__(self, config_path: str | Path | None = None):
        self.settings = Settings()
        self.providers = self._load_providers_config(config_path)
        self._apply_env_keys()

    def _load_providers_config(self, config_path: str | Path | None) -> ProvidersConfig:
        """Load provider configuration from YAML file or use defaults."""
        if config_path is None:
            # Try default locations
            for path in ["config.yaml", "config.yml", "captain_search.yaml"]:
                if Path(path).exists():
                    config_path = path
                    break

        if config_path and Path(config_path).exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            providers_data = data.get("providers", {})
            return ProvidersConfig(**providers_data)

        return ProvidersConfig()

    def _apply_env_keys(self) -> None:
        """Apply API keys from environment to provider configs."""
        if self.settings.serper_api_key:
            self.providers.serper.api_key = self.settings.serper_api_key

        if self.settings.brave_api_key:
            self.providers.brave.api_key = self.settings.brave_api_key

        if self.settings.tavily_api_key:
            self.providers.tavily.api_key = self.settings.tavily_api_key
            # Add second key if available
            if self.settings.tavily_api_key_2:
                self.providers.tavily.api_keys = [
                    self.settings.tavily_api_key,
                    self.settings.tavily_api_key_2,
                ]

        if self.settings.perplexity_api_key:
            self.providers.perplexity.api_key = self.settings.perplexity_api_key

        if self.settings.jina_api_key:
            self.providers.jina.api_key = self.settings.jina_api_key

        if self.settings.exa_api_key:
            self.providers.exa.api_key = self.settings.exa_api_key

    def get_enabled_providers(self) -> list[str]:
        """Get list of enabled providers with valid API keys."""
        enabled = []
        for name in ["serper", "brave", "tavily", "perplexity", "exa"]:
            provider = getattr(self.providers, name)
            if provider.enabled and (provider.api_key or provider.api_keys):
                enabled.append(name)
        # exa_mcp is special - works without API key via free MCP endpoint
        if self.providers.exa_mcp.enabled:
            enabled.append("exa_mcp")
        return enabled

    def get_provider_weights(self) -> dict[str, int]:
        """Get weights for all enabled providers."""
        weights = {}
        for name in self.get_enabled_providers():
            provider = getattr(self.providers, name)
            weights[name] = provider.weight
        return weights


# Global config instance (lazy initialization)
_config: Config | None = None


def get_config(config_path: str | Path | None = None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config(config_path)
    return _config


def reset_config() -> None:
    """Reset the global config (useful for testing)."""
    global _config
    _config = None
