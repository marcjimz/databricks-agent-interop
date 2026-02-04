"""Unit tests for trace tag models."""

import sys
import os
import pytest
from pydantic import ValidationError

# Add gateway directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "gateway"))


class TestGatewayTags:
    """Tests for GatewayTags model."""

    def test_gateway_tags_creation(self):
        """GatewayTags accepts required fields."""
        from models.trace import GatewayTags

        tags = GatewayTags(
            version="1.0.0",
            environment="dev",
            instance_id="gw-123"
        )
        assert tags.version == "1.0.0"
        assert tags.environment == "dev"
        assert tags.instance_id == "gw-123"

    def test_gateway_tags_missing_field_raises(self):
        """GatewayTags requires all fields."""
        from models.trace import GatewayTags

        with pytest.raises(ValidationError):
            GatewayTags(version="1.0.0")

    def test_gateway_tags_to_dict(self):
        """GatewayTags converts to flat dict with prefix."""
        from models.trace import GatewayTags

        tags = GatewayTags(
            version="1.0.0",
            environment="prod",
            instance_id="gw-456"
        )
        result = tags.to_tags_dict()

        assert result["gateway.version"] == "1.0.0"
        assert result["gateway.environment"] == "prod"
        assert result["gateway.instance_id"] == "gw-456"


class TestUserTags:
    """Tests for UserTags model."""

    def test_user_tags_with_email(self):
        """UserTags captures authenticated user."""
        from models.trace import UserTags

        tags = UserTags(email="user@company.com", authenticated=True)
        assert tags.email == "user@company.com"
        assert tags.authenticated is True

    def test_user_tags_anonymous(self):
        """UserTags defaults to anonymous."""
        from models.trace import UserTags

        tags = UserTags()
        assert tags.email is None
        assert tags.authenticated is False

    def test_user_tags_to_dict_with_email(self):
        """UserTags converts to dict with user prefix."""
        from models.trace import UserTags

        tags = UserTags(email="user@company.com", authenticated=True)
        result = tags.to_tags_dict()

        assert result["user.email"] == "user@company.com"
        assert result["user.authenticated"] == "true"

    def test_user_tags_to_dict_anonymous(self):
        """UserTags anonymous user has authenticated=false."""
        from models.trace import UserTags

        tags = UserTags()
        result = tags.to_tags_dict()

        assert "user.email" not in result
        assert result["user.authenticated"] == "false"


class TestAgentTags:
    """Tests for AgentTags model."""

    def test_agent_tags_creation(self):
        """AgentTags captures agent context."""
        from models.trace import AgentTags

        tags = AgentTags(
            name="echo-agent",
            connection_id="conn_echo",
            url="https://echo.example.com",
            method="send_message"
        )
        assert tags.name == "echo-agent"
        assert tags.connection_id == "conn_echo"
        assert tags.url == "https://echo.example.com"
        assert tags.method == "send_message"

    def test_agent_tags_valid_methods(self):
        """AgentTags accepts valid A2A methods."""
        from models.trace import AgentTags

        for method in ["send_message", "get_task", "cancel_task", "message_stream"]:
            tags = AgentTags(
                name="test",
                connection_id="conn",
                url="https://test.com",
                method=method
            )
            assert tags.method == method

    def test_agent_tags_to_dict(self):
        """AgentTags converts to dict with agent prefix."""
        from models.trace import AgentTags

        tags = AgentTags(
            name="calculator-agent",
            connection_id="conn_calc",
            url="https://calc.example.com",
            method="send_message"
        )
        result = tags.to_tags_dict()

        assert result["agent.name"] == "calculator-agent"
        assert result["agent.connection_id"] == "conn_calc"
        assert result["agent.url"] == "https://calc.example.com"
        assert result["agent.method"] == "send_message"


class TestRequestTags:
    """Tests for RequestTags model."""

    def test_request_tags_agent_proxy(self):
        """RequestTags for agent proxy request."""
        from models.trace import RequestTags

        tags = RequestTags(id="req-123", type="agent_proxy")
        assert tags.id == "req-123"
        assert tags.type == "agent_proxy"

    def test_request_tags_gateway(self):
        """RequestTags for gateway request."""
        from models.trace import RequestTags

        tags = RequestTags(id="req-456", type="gateway")
        assert tags.type == "gateway"

    def test_request_tags_health(self):
        """RequestTags for health check request."""
        from models.trace import RequestTags

        tags = RequestTags(id="req-789", type="health")
        assert tags.type == "health"

    def test_request_tags_to_dict(self):
        """RequestTags converts to dict with request prefix."""
        from models.trace import RequestTags

        tags = RequestTags(id="req-abc", type="agent_proxy")
        result = tags.to_tags_dict()

        assert result["request.id"] == "req-abc"
        assert result["request.type"] == "agent_proxy"


class TestTraceTags:
    """Tests for TraceTags composite model."""

    def test_trace_tags_minimal(self):
        """TraceTags with only required fields."""
        from models.trace import TraceTags, GatewayTags, RequestTags

        tags = TraceTags(
            gateway=GatewayTags(
                version="1.0.0",
                environment="dev",
                instance_id="gw-123"
            ),
            request=RequestTags(id="req-123", type="gateway")
        )
        assert tags.user is None
        assert tags.agent is None

    def test_trace_tags_full(self):
        """TraceTags with all fields populated."""
        from models.trace import (
            TraceTags,
            GatewayTags,
            RequestTags,
            UserTags,
            AgentTags,
        )

        tags = TraceTags(
            gateway=GatewayTags(
                version="1.0.0",
                environment="prod",
                instance_id="gw-456"
            ),
            request=RequestTags(id="req-789", type="agent_proxy"),
            user=UserTags(email="user@company.com", authenticated=True),
            agent=AgentTags(
                name="calculator-agent",
                connection_id="conn_calc",
                url="https://calc.example.com",
                method="send_message"
            )
        )
        assert tags.user.email == "user@company.com"
        assert tags.agent.name == "calculator-agent"

    def test_to_mlflow_tags_flattens_structure(self):
        """to_mlflow_tags() returns flat dict with dot notation."""
        from models.trace import (
            TraceTags,
            GatewayTags,
            RequestTags,
            AgentTags,
        )

        tags = TraceTags(
            gateway=GatewayTags(
                version="1.0.0",
                environment="dev",
                instance_id="gw-123"
            ),
            request=RequestTags(id="req-123", type="agent_proxy"),
            agent=AgentTags(
                name="echo-agent",
                connection_id="conn_echo",
                url="https://echo.example.com",
                method="send_message"
            )
        )
        mlflow_tags = tags.to_mlflow_tags()

        assert mlflow_tags["gateway.version"] == "1.0.0"
        assert mlflow_tags["gateway.environment"] == "dev"
        assert mlflow_tags["gateway.instance_id"] == "gw-123"
        assert mlflow_tags["request.id"] == "req-123"
        assert mlflow_tags["request.type"] == "agent_proxy"
        assert mlflow_tags["agent.name"] == "echo-agent"
        assert mlflow_tags["agent.connection_id"] == "conn_echo"

    def test_to_mlflow_tags_excludes_none_values(self):
        """to_mlflow_tags() omits None fields."""
        from models.trace import TraceTags, GatewayTags, RequestTags

        tags = TraceTags(
            gateway=GatewayTags(
                version="1.0.0",
                environment="dev",
                instance_id="gw-123"
            ),
            request=RequestTags(id="req-123", type="gateway")
        )
        mlflow_tags = tags.to_mlflow_tags()

        assert "agent.name" not in mlflow_tags
        assert "agent.connection_id" not in mlflow_tags
        assert "agent.url" not in mlflow_tags
        assert "agent.method" not in mlflow_tags

    def test_to_mlflow_tags_includes_user_when_present(self):
        """to_mlflow_tags() includes user tags when present."""
        from models.trace import (
            TraceTags,
            GatewayTags,
            RequestTags,
            UserTags,
        )

        tags = TraceTags(
            gateway=GatewayTags(
                version="1.0.0",
                environment="dev",
                instance_id="gw-123"
            ),
            request=RequestTags(id="req-123", type="gateway"),
            user=UserTags(email="test@example.com", authenticated=True)
        )
        mlflow_tags = tags.to_mlflow_tags()

        assert mlflow_tags["user.email"] == "test@example.com"
        assert mlflow_tags["user.authenticated"] == "true"

    def test_to_mlflow_tags_anonymous_user(self):
        """to_mlflow_tags() handles anonymous user correctly."""
        from models.trace import (
            TraceTags,
            GatewayTags,
            RequestTags,
            UserTags,
        )

        tags = TraceTags(
            gateway=GatewayTags(
                version="1.0.0",
                environment="dev",
                instance_id="gw-123"
            ),
            request=RequestTags(id="req-123", type="gateway"),
            user=UserTags()  # Anonymous
        )
        mlflow_tags = tags.to_mlflow_tags()

        assert "user.email" not in mlflow_tags
        assert mlflow_tags["user.authenticated"] == "false"
