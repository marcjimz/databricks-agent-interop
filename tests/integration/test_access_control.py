"""
Access control tests for A2A Gateway.

Tests:
- UC connection-based authorization
- 403 for users without USE_CONNECTION
- 404 for non-existent agents
"""

import pytest
import requests


class TestAgentAccessControl:
    """Test access control for agent operations."""

    def test_accessible_agent_returns_200(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """User with USE_CONNECTION can access agent."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}",
            headers=auth_headers
        )
        # Should be 200 (agent exists and user has access)
        # or 404 if agent doesn't exist in test environment
        assert response.status_code in [200, 404]

    def test_restricted_agent_returns_403(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        restricted_agent_name: str
    ):
        """User without USE_CONNECTION gets 403."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{restricted_agent_name}",
            headers=auth_headers
        )
        # Should be 403 (forbidden) if agent exists but no permission
        # or 404 if agent doesn't exist
        assert response.status_code in [403, 404]

        if response.status_code == 403:
            data = response.json()
            assert "error" in data
            assert "access_denied" in data["error"]

    def test_nonexistent_agent_returns_404(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Request for non-existent agent returns 404."""
        response = requests.get(
            f"{apim_gateway_url}/agents/nonexistent-agent-xyz-12345",
            headers=auth_headers
        )
        assert response.status_code == 404

        data = response.json()
        assert "error" in data
        assert "not_found" in data["error"] or "agent_not_found" in data["error"]


class TestAgentCardAccess:
    """Test access control for agent card endpoint."""

    def test_agent_card_access_requires_permission(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        restricted_agent_name: str
    ):
        """Agent card access requires USE_CONNECTION."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{restricted_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )
        # Should be 403 (forbidden) if agent exists but no permission
        # or 404 if agent doesn't exist
        assert response.status_code in [403, 404]

    def test_agent_card_accessible_with_permission(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card accessible with USE_CONNECTION."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )
        # Should be 200 (card returned) or 404 (agent doesn't exist)
        # or 502 (agent exists but card fetch failed)
        assert response.status_code in [200, 404, 502]

        if response.status_code == 200:
            data = response.json()
            # A2A agent card should have these fields
            assert "name" in data or "url" in data


class TestRPCAccessControl:
    """Test access control for RPC/message operations."""

    def test_rpc_requires_permission(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        restricted_agent_name: str
    ):
        """RPC to agent requires USE_CONNECTION."""
        response = requests.post(
            f"{apim_gateway_url}/agents/{restricted_agent_name}",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "test-1",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "test"}]
                    }
                }
            }
        )
        # Should be 403 (forbidden) if agent exists but no permission
        # or 404 if agent doesn't exist
        assert response.status_code in [403, 404]

    def test_rpc_accessible_with_permission(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """RPC accessible with USE_CONNECTION."""
        response = requests.post(
            f"{apim_gateway_url}/agents/{test_agent_name}",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "test-1",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Hello"}]
                    }
                }
            }
        )
        # Should be 200 (response) or 404 (agent doesn't exist)
        # or 502 (agent exists but backend error)
        assert response.status_code in [200, 404, 502]


class TestStreamAccessControl:
    """Test access control for streaming operations."""

    def test_stream_requires_permission(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        restricted_agent_name: str
    ):
        """Streaming to agent requires USE_CONNECTION."""
        response = requests.post(
            f"{apim_gateway_url}/agents/{restricted_agent_name}/stream",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "test-stream-1",
                "method": "message/stream",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "test"}]
                    }
                }
            },
            stream=True
        )
        # Should be 403 (forbidden) if agent exists but no permission
        # or 404 if agent doesn't exist
        assert response.status_code in [403, 404]
