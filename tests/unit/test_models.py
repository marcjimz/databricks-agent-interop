"""Unit tests for gateway models."""

import pytest
from pydantic import ValidationError

# Add gateway to path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "gateway"))

from models import AgentInfo, OAuthM2MCredentials, AgentListResponse, HealthResponse


class TestAgentInfo:
    """Tests for AgentInfo model."""

    def test_minimal_agent_info(self):
        """Test creating AgentInfo with minimal required fields."""
        agent = AgentInfo(
            name="test-agent",
            agent_card_url="https://example.com/.well-known/agent.json",
            connection_name="test-agent-a2a",
            catalog="main",
            schema_name="default"
        )
        assert agent.name == "test-agent"
        assert agent.agent_card_url == "https://example.com/.well-known/agent.json"
        assert agent.connection_name == "test-agent-a2a"
        assert agent.catalog == "main"
        assert agent.schema_name == "default"
        assert agent.description is None
        assert agent.bearer_token is None
        assert agent.oauth_m2m is None

    def test_agent_info_with_description(self):
        """Test AgentInfo with description."""
        agent = AgentInfo(
            name="test-agent",
            description="A test agent",
            agent_card_url="https://example.com/.well-known/agent.json",
            connection_name="test-agent-a2a",
            catalog="main",
            schema_name="default"
        )
        assert agent.description == "A test agent"

    def test_agent_info_with_bearer_token(self):
        """Test AgentInfo with bearer token."""
        agent = AgentInfo(
            name="test-agent",
            agent_card_url="https://example.com/.well-known/agent.json",
            connection_name="test-agent-a2a",
            catalog="main",
            schema_name="default",
            bearer_token="my-secret-token"
        )
        assert agent.bearer_token == "my-secret-token"

    def test_agent_info_with_oauth_m2m(self):
        """Test AgentInfo with OAuth M2M credentials."""
        oauth = OAuthM2MCredentials(
            client_id="client-123",
            client_secret="secret-456",
            token_endpoint="https://auth.example.com/token"
        )
        agent = AgentInfo(
            name="test-agent",
            agent_card_url="https://example.com/.well-known/agent.json",
            connection_name="test-agent-a2a",
            catalog="main",
            schema_name="default",
            oauth_m2m=oauth
        )
        assert agent.oauth_m2m is not None
        assert agent.oauth_m2m.client_id == "client-123"


class TestOAuthM2MCredentials:
    """Tests for OAuthM2MCredentials model."""

    def test_oauth_credentials_required_fields(self):
        """Test OAuth credentials with required fields."""
        oauth = OAuthM2MCredentials(
            client_id="client-123",
            client_secret="secret-456",
            token_endpoint="https://auth.example.com/token"
        )
        assert oauth.client_id == "client-123"
        assert oauth.client_secret == "secret-456"
        assert oauth.token_endpoint == "https://auth.example.com/token"
        assert oauth.oauth_scope is None

    def test_oauth_credentials_with_scope(self):
        """Test OAuth credentials with scope."""
        oauth = OAuthM2MCredentials(
            client_id="client-123",
            client_secret="secret-456",
            token_endpoint="https://auth.example.com/token",
            oauth_scope="read write"
        )
        assert oauth.oauth_scope == "read write"


class TestAgentListResponse:
    """Tests for AgentListResponse model."""

    def test_empty_agent_list(self):
        """Test empty agent list response."""
        response = AgentListResponse(agents=[], total=0)
        assert response.agents == []
        assert response.total == 0

    def test_agent_list_with_agents(self):
        """Test agent list with multiple agents."""
        agents = [
            AgentInfo(
                name="agent-1",
                agent_card_url="https://example.com/agent1/.well-known/agent.json",
                connection_name="agent-1-a2a",
                catalog="main",
                schema_name="default"
            ),
            AgentInfo(
                name="agent-2",
                agent_card_url="https://example.com/agent2/.well-known/agent.json",
                connection_name="agent-2-a2a",
                catalog="main",
                schema_name="default"
            )
        ]
        response = AgentListResponse(agents=agents, total=2)
        assert len(response.agents) == 2
        assert response.total == 2


class TestHealthResponse:
    """Tests for HealthResponse model."""

    def test_health_response(self):
        """Test health response model."""
        health = HealthResponse(status="healthy", version="1.0.0")
        assert health.status == "healthy"
        assert health.version == "1.0.0"
