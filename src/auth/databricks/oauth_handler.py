"""
Databricks OAuth U2M (User-to-Machine) Handler.

Implements the OAuth authorization code flow with PKCE for secure
user authentication against Databricks workspaces.

Based on: https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m

Usage:
    from src.auth.databricks import DatabricksOAuthHandler

    # Interactive flow (opens browser)
    handler = DatabricksOAuthHandler(host="https://your-workspace.cloud.databricks.com")
    token = handler.get_token(scopes=["catalog.connections"])

    # Using refresh token (no browser)
    token = handler.refresh_token(refresh_token="...")
"""

import base64
import hashlib
import json
import secrets
import string
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests


# Default OAuth client ID (Databricks CLI - public client)
DEFAULT_CLIENT_ID = "databricks-cli"
DEFAULT_REDIRECT_URI = "http://localhost:8020"


@dataclass
class OAuthToken:
    """OAuth token response."""
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
    scope: Optional[str] = None

    @classmethod
    def from_response(cls, data: dict) -> "OAuthToken":
        """Create from token endpoint response."""
        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=data.get("expires_in", 3600),
            refresh_token=data.get("refresh_token"),
            scope=data.get("scope"),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "refresh_token": self.refresh_token,
            "scope": self.scope,
        }


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture OAuth callback."""

    authorization_code: Optional[str] = None
    state_value: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self):
        """Handle GET request from OAuth callback."""
        query_components = parse_qs(urlparse(self.path).query)

        _OAuthCallbackHandler.authorization_code = query_components.get("code", [None])[0]
        _OAuthCallbackHandler.state_value = query_components.get("state", [None])[0]
        _OAuthCallbackHandler.error = query_components.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        if _OAuthCallbackHandler.authorization_code:
            message = """
            <html><body>
                <h2>Authorization Successful!</h2>
                <p>You can close this window and return to the terminal.</p>
            </body></html>
            """
        else:
            error_msg = _OAuthCallbackHandler.error or "Unknown error"
            message = f"""
            <html><body>
                <h2>Authorization Failed</h2>
                <p>Error: {error_msg}</p>
            </body></html>
            """

        self.wfile.write(message.encode())

    def log_message(self, format, *args):
        """Suppress log messages."""
        pass


class DatabricksOAuthHandler:
    """
    Databricks OAuth U2M authentication handler.

    Supports:
    - Authorization code flow with PKCE (browser-based)
    - Token refresh (non-interactive)
    """

    def __init__(
        self,
        host: str,
        client_id: str = DEFAULT_CLIENT_ID,
        redirect_uri: str = DEFAULT_REDIRECT_URI,
    ):
        """
        Initialize OAuth handler.

        Args:
            host: Databricks workspace URL (e.g., https://your-workspace.cloud.databricks.com)
            client_id: OAuth client ID (default: databricks-cli)
            redirect_uri: Redirect URI for callback (default: http://localhost:8020)
        """
        self.host = host.rstrip("/")
        self.client_id = client_id
        self.redirect_uri = redirect_uri

        # OIDC endpoints
        self.authorize_url = f"{self.host}/oidc/v1/authorize"
        self.token_url = f"{self.host}/oidc/v1/token"

    @staticmethod
    def _generate_pkce_pair() -> tuple[str, str]:
        """
        Generate PKCE code verifier and challenge.

        Returns:
            Tuple of (code_verifier, code_challenge)
        """
        allowed_chars = string.ascii_letters + string.digits + "-._~"
        code_verifier = "".join(secrets.choice(allowed_chars) for _ in range(64))

        sha256_hash = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")

        return code_verifier, code_challenge

    def _build_auth_url(self, scopes: List[str], code_challenge: str, state: str) -> str:
        """Build the authorization URL."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(scopes),
        }
        return f"{self.authorize_url}?{urlencode(params)}"

    def _wait_for_callback(self) -> str:
        """Start local server and wait for OAuth callback."""
        # Reset handler state
        _OAuthCallbackHandler.authorization_code = None
        _OAuthCallbackHandler.state_value = None
        _OAuthCallbackHandler.error = None

        port = int(urlparse(self.redirect_uri).port or 8020)
        server = HTTPServer(("localhost", port), _OAuthCallbackHandler)
        server.handle_request()

        if _OAuthCallbackHandler.error:
            raise ValueError(f"OAuth error: {_OAuthCallbackHandler.error}")

        if not _OAuthCallbackHandler.authorization_code:
            raise ValueError("No authorization code received")

        return _OAuthCallbackHandler.authorization_code

    def _exchange_code(
        self,
        code: str,
        code_verifier: str,
        scopes: List[str],
    ) -> OAuthToken:
        """Exchange authorization code for tokens."""
        data = {
            "client_id": self.client_id,
            "grant_type": "authorization_code",
            "scope": " ".join(scopes),
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
            "code": code,
        }

        response = requests.post(self.token_url, data=data)

        if response.status_code != 200:
            raise ValueError(f"Token exchange failed: {response.status_code} - {response.text}")

        return OAuthToken.from_response(response.json())

    def get_token(
        self,
        scopes: Optional[List[str]] = None,
        open_browser: bool = True,
    ) -> OAuthToken:
        """
        Get OAuth token using browser-based authorization flow.

        Args:
            scopes: OAuth scopes to request (default: ["all-apis", "offline_access"])
            open_browser: Whether to automatically open browser (default: True)

        Returns:
            OAuthToken with access_token and optional refresh_token
        """
        if scopes is None:
            scopes = ["all-apis", "offline_access"]

        # Generate PKCE pair
        code_verifier, code_challenge = self._generate_pkce_pair()

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        # Build authorization URL
        auth_url = self._build_auth_url(scopes, code_challenge, state)

        print(f"Opening browser for authorization...")
        print(f"If browser doesn't open, visit: {auth_url}\n")

        if open_browser:
            webbrowser.open(auth_url)

        print(f"Waiting for callback on {self.redirect_uri}...")

        # Wait for callback
        auth_code = self._wait_for_callback()

        # Validate state
        if _OAuthCallbackHandler.state_value != state:
            raise ValueError("State mismatch - possible CSRF attack")

        print("Authorization received, exchanging for token...")

        # Exchange code for token
        return self._exchange_code(auth_code, code_verifier, scopes)

    def refresh_token(self, refresh_token: str) -> OAuthToken:
        """
        Get new access token using refresh token (no browser needed).

        Args:
            refresh_token: The refresh token from a previous authorization

        Returns:
            OAuthToken with new access_token
        """
        data = {
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        response = requests.post(self.token_url, data=data)

        if response.status_code != 200:
            raise ValueError(f"Token refresh failed: {response.status_code} - {response.text}")

        return OAuthToken.from_response(response.json())


def main():
    """CLI entrypoint for testing."""
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="Generate Databricks OAuth token")
    parser.add_argument(
        "--host",
        default=os.environ.get("DATABRICKS_HOST"),
        help="Databricks workspace URL (or set DATABRICKS_HOST env var)",
    )
    parser.add_argument(
        "--scopes",
        default="catalog.connections",
        help="Space-separated OAuth scopes (default: catalog.connections)",
    )
    parser.add_argument(
        "--refresh-token",
        help="Use refresh token instead of browser auth",
    )
    parser.add_argument(
        "--client-id",
        default=DEFAULT_CLIENT_ID,
        help=f"OAuth client ID (default: {DEFAULT_CLIENT_ID})",
    )
    parser.add_argument(
        "--redirect-uri",
        default=DEFAULT_REDIRECT_URI,
        help=f"Redirect URI (default: {DEFAULT_REDIRECT_URI})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    args = parser.parse_args()

    if not args.host:
        print("Error: --host required or set DATABRICKS_HOST", file=sys.stderr)
        sys.exit(1)

    print(f"Host: {args.host}", file=sys.stderr)
    print(f"Client ID: {args.client_id}", file=sys.stderr)
    print(f"Redirect URI: {args.redirect_uri}", file=sys.stderr)

    handler = DatabricksOAuthHandler(
        host=args.host,
        client_id=args.client_id,
        redirect_uri=args.redirect_uri,
    )

    try:
        if args.refresh_token:
            token = handler.refresh_token(args.refresh_token)
        else:
            scopes = args.scopes.split()
            token = handler.get_token(scopes=scopes)

        if args.json:
            print(json.dumps(token.to_dict(), indent=2))
        else:
            print(f"\nAccess Token:\n{token.access_token}")
            if token.refresh_token:
                print(f"\nRefresh Token:\n{token.refresh_token}")
            print(f"\nExpires in: {token.expires_in}s")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
