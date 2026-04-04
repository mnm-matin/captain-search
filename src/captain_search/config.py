"""Configuration management for search-proxy."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings


def _parse_api_keys(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item and item.strip()]


def _merge_api_keys(*values: str | list[str] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        items = [value] if isinstance(value, str) else list(value or [])
        for item in items:
            cleaned = item.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            merged.append(cleaned)
    return merged


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
    parallel: ProviderConfig = Field(default_factory=lambda: ProviderConfig(weight=0, enabled=True))
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
    serper_api_keys: str | None = Field(default=None, alias="SERPER_API_KEYS")
    brave_api_key: str | None = Field(default=None, alias="BRAVE_API_KEY")
    brave_api_keys: str | None = Field(default=None, alias="BRAVE_API_KEYS")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    tavily_api_keys: str | None = Field(default=None, alias="TAVILY_API_KEYS")
    perplexity_api_key: str | None = Field(default=None, alias="PERPLEXITY_API_KEY")
    perplexity_api_keys: str | None = Field(default=None, alias="PERPLEXITY_API_KEYS")
    parallel_api_key: str | None = Field(default=None, alias="PARALLEL_API_KEY")
    parallel_api_keys: str | None = Field(default=None, alias="PARALLEL_API_KEYS")
    jina_api_key: str | None = Field(default=None, alias="JINA_API_KEY")
    jina_api_keys: str | None = Field(default=None, alias="JINA_API_KEYS")
    exa_api_key: str | None = Field(default=None, alias="EXA_API_KEY")
    exa_api_keys: str | None = Field(default=None, alias="EXA_API_KEYS")
    morph_api_key: str | None = Field(default=None, alias="MORPH_API_KEY")
    morph_base_url: str = Field(
        default="https://api.morphllm.com",
        alias="MORPH_BASE_URL",
        validation_alias=AliasChoices("MORPH_BASE_URL", "MORPH_API_URL"),
    )

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
    captain_search_log_enabled: bool = Field(default=True, alias="CAPTAIN_SEARCH_LOG_ENABLED")
    captain_search_log_dir: str = Field(
        default=str(Path.home() / ".captain-search" / "logs"),
        alias="CAPTAIN_SEARCH_LOG_DIR",
    )
    captain_search_log_full_payloads: bool = Field(
        default=False,
        alias="CAPTAIN_SEARCH_LOG_FULL_PAYLOADS",
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
        for provider_name in ("serper", "brave", "tavily", "perplexity", "parallel", "jina", "exa"):
            provider = getattr(self.providers, provider_name)
            env_api_key = getattr(self.settings, f"{provider_name}_api_key")
            env_api_keys = _parse_api_keys(getattr(self.settings, f"{provider_name}_api_keys"))
            merged = _merge_api_keys(
                env_api_key,
                env_api_keys,
                provider.api_key,
                provider.api_keys,
            )
            provider.api_keys = merged
            provider.api_key = merged[0] if merged else None

        exa_mcp = self.providers.exa_mcp
        exa_mcp_keys = _merge_api_keys(
            self.settings.exa_api_key,
            _parse_api_keys(self.settings.exa_api_keys),
            exa_mcp.api_key,
            exa_mcp.api_keys,
        )
        exa_mcp.api_keys = exa_mcp_keys
        exa_mcp.api_key = exa_mcp_keys[0] if exa_mcp_keys else None

    def get_enabled_providers(self) -> list[str]:
        """Get list of enabled providers with valid API keys."""
        enabled = []
        for name in ["serper", "brave", "tavily", "perplexity", "parallel", "exa"]:
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
