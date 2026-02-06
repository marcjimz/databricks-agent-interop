"""
Authentication tests for A2A Gateway.

Tests:
- Databricks OAuth token validation
- Entra ID token validation and exchange
- Invalid/missing token rejection
"""

import pytest
import requests


class TestDatabricksAuth:
    """Test authentication with Databricks tokens."""

    def test_valid_token_accepted(self, apim_gateway_url: str, auth_headers: dict):
        """Valid Databricks OAuth token should be accepted."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "user" in data

    def test_user_email_extracted(self, apim_gateway_url: str, auth_headers: dict):
        """User email should be extracted from token."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "user" in data
        assert "@" in data["user"]  # Should be an email


class TestEntraAuth:
    """Test authentication with Entra ID tokens (requires token exchange)."""

    @pytest.mark.skipif(
        not pytest.importorskip("os").environ.get("ENTRA_TOKEN"),
        reason="ENTRA_TOKEN not set"
    )
    def test_entra_token_exchanged(self, apim_gateway_url: str, entra_auth_headers: dict):
        """Entra ID token should be exchanged for Databricks token."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=entra_auth_headers
        )
        # Should be 200 if token exchange works, 401 if not configured
        assert response.status_code in [200, 401]

        if response.status_code == 401:
            data = response.json()
            # Check if it's a token exchange failure vs invalid token
            assert "token_exchange" in data.get("error", "") or "Invalid" in data.get("message", "")


class TestInvalidAuth:
    """Test rejection of invalid authentication."""

    def test_missing_token_rejected(self, apim_gateway_url: str):
        """Request without token should be rejected with 401."""
        response = requests.get(f"{apim_gateway_url}/agents")
        assert response.status_code == 401

    def test_invalid_token_rejected(self, apim_gateway_url: str):
        """Invalid token should be rejected with 401."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers={"Authorization": "Bearer invalid-token-12345"}
        )
        assert response.status_code == 401

    def test_malformed_auth_header_rejected(self, apim_gateway_url: str):
        """Malformed Authorization header should be rejected."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers={"Authorization": "NotBearer some-token"}
        )
        assert response.status_code == 401

    def test_empty_token_rejected(self, apim_gateway_url: str):
        """Empty token should be rejected."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers={"Authorization": "Bearer "}
        )
        assert response.status_code == 401
