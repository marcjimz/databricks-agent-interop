"""Integration tests for the A2A Gateway API."""

import pytest
from tests.conftest import make_a2a_message


class TestGatewayHealth:
    """Tests for gateway health and info endpoints."""

    def test_root_endpoint(self, http_client, gateway_url):
        """Test the root endpoint returns gateway info."""
        response = http_client.get(f"{gateway_url}/")
        assert response.status_code == 200

        data = response.json()
        assert "name" in data
        assert "version" in data
        assert data["status"] == "healthy"

    def test_health_endpoint(self, http_client, gateway_url):
        """Test the health check endpoint."""
        response = http_client.get(f"{gateway_url}/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"

    def test_agent_card(self, http_client, gateway_url):
        """Test the gateway's own agent card."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        assert response.status_code == 200

        data = response.json()
        assert "name" in data
        assert "capabilities" in data
        assert "skills" in data


class TestAgentDiscovery:
    """Tests for agent discovery endpoints."""

    def test_list_agents(self, http_client, gateway_url):
        """Test listing accessible agents."""
        response = http_client.get(f"{gateway_url}/api/agents")
        assert response.status_code == 200

        data = response.json()
        assert "agents" in data
        assert "total" in data
        assert isinstance(data["agents"], list)

    def test_list_agents_returns_accessible_only(self, http_client, gateway_url):
        """Test that only accessible agents are returned."""
        response = http_client.get(f"{gateway_url}/api/agents")
        assert response.status_code == 200

        data = response.json()
        # Each agent should have required fields
        for agent in data["agents"]:
            assert "name" in agent
            assert "connection_name" in agent
            assert "agent_card_url" in agent


class TestAgentInfo:
    """Tests for getting individual agent information."""

    def test_get_agent_not_found(self, http_client, gateway_url):
        """Test getting a non-existent agent."""
        response = http_client.get(f"{gateway_url}/api/agents/nonexistent-agent")
        assert response.status_code == 404

        data = response.json()
        assert "error" in data


class TestAuthentication:
    """Tests for authentication handling."""

    def test_valid_token_succeeds(self, http_client, gateway_url):
        """Test that a valid token allows access."""
        response = http_client.get(f"{gateway_url}/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "total" in data

    def test_valid_token_returns_user_agents(self, http_client, gateway_url):
        """Test that valid token returns agents the user has access to."""
        response = http_client.get(f"{gateway_url}/api/agents")
        assert response.status_code == 200
        data = response.json()
        # User should have access to at least some agents (or empty list if none)
        assert isinstance(data["agents"], list)
        assert isinstance(data["total"], int)
        assert data["total"] == len(data["agents"])

    def test_invalid_token_returns_401(self, gateway_url):
        """Test that invalid token returns 401 from Databricks Apps."""
        import httpx
        client = httpx.Client(
            headers={"Authorization": "Bearer invalid-token-12345"},
            timeout=30.0
        )
        response = client.get(f"{gateway_url}/api/agents")
        # Databricks Apps returns 401 for invalid tokens
        assert response.status_code == 401

    def test_malformed_token_returns_401(self, gateway_url):
        """Test that malformed token returns 401."""
        import httpx
        client = httpx.Client(
            headers={"Authorization": "Bearer x"},  # Minimal invalid token
            timeout=30.0
        )
        response = client.get(f"{gateway_url}/api/agents")
        assert response.status_code == 401

    def test_wrong_auth_scheme_returns_401(self, gateway_url):
        """Test that wrong auth scheme returns 401."""
        import httpx
        client = httpx.Client(
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
            timeout=30.0
        )
        response = client.get(f"{gateway_url}/api/agents")
        assert response.status_code == 401

    def test_no_token_redirects(self, gateway_url):
        """Test that no token redirects to login."""
        import httpx
        client = httpx.Client(timeout=30.0, follow_redirects=False)
        response = client.get(f"{gateway_url}/api/agents")
        # Databricks Apps redirects to OAuth login
        assert response.status_code in [302, 401]

    def test_expired_token_returns_401(self, gateway_url):
        """Test that expired/revoked token returns 401."""
        import httpx
        # This is a structurally valid JWT but expired/invalid
        fake_jwt = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IlRlc3QiLCJpYXQiOjE1MTYyMzkwMjJ9.fake_signature"
        client = httpx.Client(
            headers={"Authorization": f"Bearer {fake_jwt}"},
            timeout=30.0
        )
        response = client.get(f"{gateway_url}/api/agents")
        assert response.status_code == 401
