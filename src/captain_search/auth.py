"""Authentication helpers for running Captain Search as a remote MCP server.

Design goals:
- No auth by default (easy OSS self-hosting)
- Standard HTTP auth when enabled: `Authorization: Bearer <token>`
- Optional URL query param fallback for clients that can't send headers

FastMCP already supports OAuth/OIDC providers, but for most self-hosted cases a
static bearer token is the simplest compatible option.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Sequence

from fastmcp.server.auth import AccessToken, TokenVerifier
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from starlette.authentication import AuthCredentials, AuthenticationBackend
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection

DEFAULT_QUERY_PARAM_NAMES: tuple[str, ...] = (
    "api_key",
    "token",
)


class BearerOrQueryAuthBackend(AuthenticationBackend):
    """Auth backend that accepts either Bearer headers or query param tokens.

    - Standard: `Authorization: Bearer <token>`
    - Fallback: `?api_key=<token>` (or `?token=<token>`)

    The server-side token validation logic is delegated to a TokenVerifier.
    """

    def __init__(
        self,
        token_verifier: TokenVerifier,
        *,
        query_param_names: Sequence[str] = DEFAULT_QUERY_PARAM_NAMES,
    ):
        self._token_verifier = token_verifier
        self._query_param_names = tuple(query_param_names)

    async def authenticate(self, conn: HTTPConnection):
        token: str | None = None

        auth_header = conn.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

        if not token and self._query_param_names:
            query_params = conn.query_params
            for name in self._query_param_names:
                value = query_params.get(name)
                if value:
                    token = value.strip()
                    break

        if not token:
            return None

        auth_info = await self._token_verifier.verify_token(token)
        if not auth_info:
            return None

        if auth_info.expires_at and auth_info.expires_at < int(time.time()):
            return None

        return AuthCredentials(auth_info.scopes), AuthenticatedUser(auth_info)


class StaticBearerTokenAuth(TokenVerifier):
    """A simple static-token auth provider for FastMCP.

    This is intended for self-hosted deployments where you want a single shared
    secret to protect the remote MCP endpoint.

    By default it accepts `Authorization: Bearer <token>` and also supports
    `?api_key=<token>` / `?token=<token>` as a convenience fallback.
    """

    def __init__(
        self,
        tokens: Sequence[str],
        *,
        client_id: str = "captain-search",
        allow_query_param_auth: bool = True,
        query_param_names: Sequence[str] = DEFAULT_QUERY_PARAM_NAMES,
        required_scopes: list[str] | None = None,
    ):
        super().__init__(required_scopes=required_scopes)
        self._tokens = tuple(t for t in (s.strip() for s in tokens) if t)
        if not self._tokens:
            raise ValueError("At least one non-empty token is required")

        self._client_id = client_id
        self._allow_query_param_auth = allow_query_param_auth
        self._query_param_names = tuple(query_param_names)

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None

        for expected in self._tokens:
            if secrets.compare_digest(token, expected):
                return AccessToken(
                    token=token,
                    client_id=self._client_id,
                    scopes=[],
                    expires_at=None,
                    resource=None,
                    claims={"auth": "static_bearer"},
                )

        return None

    def get_middleware(self) -> list:
        query_param_names = self._query_param_names if self._allow_query_param_auth else ()
        return [
            Middleware(
                AuthenticationMiddleware,
                backend=BearerOrQueryAuthBackend(
                    self,
                    query_param_names=query_param_names,
                ),
            ),
            Middleware(AuthContextMiddleware),
        ]


def build_auth_provider(mcp_auth_token: str | None) -> TokenVerifier | None:
    """Build an auth provider from env/config.

    If `mcp_auth_token` is unset/blank, returns None (no auth).

    Supports token rotation via comma-separated tokens:
    - MCP_AUTH_TOKEN=tok1,tok2
    """

    if not mcp_auth_token or not mcp_auth_token.strip():
        return None

    tokens = [t.strip() for t in mcp_auth_token.split(",") if t.strip()]
    return StaticBearerTokenAuth(tokens)
