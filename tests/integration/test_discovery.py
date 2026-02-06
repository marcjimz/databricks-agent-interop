"""
Discovery tests for A2A Gateway.

Tests:
- List accessible agents (GET /agents)
- Agent listing response format
- Filtering by user permissions
"""

import pytest
import requests


class TestAgentDiscovery:
    """Test agent discovery/listing functionality."""

    def test_list_agents_returns_200(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """GET /agents should return 200 with valid token."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200

    def test_list_agents_response_structure(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Response should have expected structure."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()

        # Required fields
        assert "agents" in data, "Response must have 'agents' field"
        assert "user" in data, "Response must have 'user' field"
        assert "total" in data, "Response must have 'total' field"

        # Type checks
        assert isinstance(data["agents"], list)
        assert isinstance(data["total"], int)
        assert data["total"] == len(data["agents"])

    def test_list_agents_agent_structure(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Each agent in list should have expected fields."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()

        for agent in data["agents"]:
            # Required fields for each agent
            assert "name" in agent, "Agent must have 'name' field"
            assert "url" in agent, "Agent must have 'url' field"

            # URL should be relative path
            assert agent["url"].startswith("/agents/")

            # Name should not have -a2a suffix (cleaned)
            assert not agent["name"].endswith("-a2a")

    def test_list_agents_returns_user_email(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Response should include authenticated user's email."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        user = data.get("user", "")

        # User should be an email or identifier
        assert user, "User field should not be empty"
        # Most auth flows will have an email
        if "@" in user:
            assert "." in user.split("@")[1], "User email should have valid domain"

    def test_list_agents_only_shows_accessible(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """List should only include agents user has access to."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        agent_names = [a["name"] for a in data["agents"]]

        # If test_agent_name is accessible, it should be in the list
        # Note: This test may pass vacuously if no agents configured
        if test_agent_name in agent_names:
            # Verify we can actually access it
            agent_response = requests.get(
                f"{apim_gateway_url}/agents/{test_agent_name}",
                headers=auth_headers
            )
            assert agent_response.status_code == 200


class TestDiscoveryErrors:
    """Test error handling for discovery endpoint."""

    def test_list_agents_requires_auth(self, apim_gateway_url: str):
        """GET /agents without auth should return 401."""
        response = requests.get(f"{apim_gateway_url}/agents")
        assert response.status_code == 401

    def test_list_agents_content_type(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Response should be JSON."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert "application/json" in response.headers.get("Content-Type", "")
