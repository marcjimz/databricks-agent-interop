"""
Unit tests for agent connection creation script.

Tests:
- UC HTTP connection creation
- Connection naming conventions
- Options configuration
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class MockConnectionResponse:
    """Mock Databricks connection response."""

    def __init__(
        self,
        name: str = "test-agent-a2a",
        full_name: str = "catalog.schema.test-agent-a2a",
        owner: str = "test-user@example.com",
        connection_type: str = "HTTP",
        comment: str = "Test agent",
        options: dict = None
    ):
        self.name = name
        self.full_name = full_name
        self.owner = owner
        self.connection_type = connection_type
        self.comment = comment
        self.options = options or {
            "host": "https://test.example.com",
            "port": "443",
            "base_path": "/a2a"
        }


class TestConnectionNaming:
    """Test connection naming conventions."""

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_connection_name_suffix(self, mock_ws_class):
        """Connection name should have -a2a suffix."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse(
            name="my-agent-a2a"
        )

        result = create_a2a_connection(
            agent_name="my-agent",
            host="https://test.example.com"
        )

        # Verify connection created with -a2a suffix
        call_args = mock_ws.connections.create.call_args
        assert call_args.kwargs["name"] == "my-agent-a2a"

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_agent_name_without_suffix(self, mock_ws_class):
        """Agent name should not include -a2a suffix."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        # Calling with agent name (not connection name)
        create_a2a_connection(
            agent_name="echo",  # Not "echo-a2a"
            host="https://test.example.com"
        )

        call_args = mock_ws.connections.create.call_args
        assert call_args.kwargs["name"] == "echo-a2a"


class TestConnectionOptions:
    """Test HTTP connection options."""

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_host_option_set(self, mock_ws_class):
        """Host should be set in connection options."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        create_a2a_connection(
            agent_name="test",
            host="https://my-backend.example.com"
        )

        call_args = mock_ws.connections.create.call_args
        options = call_args.kwargs["options"]
        assert options["host"] == "https://my-backend.example.com"

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_default_base_path(self, mock_ws_class):
        """Default base_path should be /a2a."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        create_a2a_connection(
            agent_name="test",
            host="https://test.example.com"
        )

        call_args = mock_ws.connections.create.call_args
        options = call_args.kwargs["options"]
        assert options["base_path"] == "/a2a"

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_custom_base_path(self, mock_ws_class):
        """Custom base_path should be respected."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        create_a2a_connection(
            agent_name="test",
            host="https://test.example.com",
            base_path="/custom/path"
        )

        call_args = mock_ws.connections.create.call_args
        options = call_args.kwargs["options"]
        assert options["base_path"] == "/custom/path"

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_default_port(self, mock_ws_class):
        """Default port should be 443."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        create_a2a_connection(
            agent_name="test",
            host="https://test.example.com"
        )

        call_args = mock_ws.connections.create.call_args
        options = call_args.kwargs["options"]
        assert options["port"] == "443"

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_databricks_bearer_token(self, mock_ws_class):
        """Default bearer_token should be 'databricks' for passthrough."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        create_a2a_connection(
            agent_name="test",
            host="https://test.example.com"
        )

        call_args = mock_ws.connections.create.call_args
        options = call_args.kwargs["options"]
        assert options["bearer_token"] == "databricks"

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_custom_bearer_token(self, mock_ws_class):
        """Custom bearer_token should be set."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        create_a2a_connection(
            agent_name="test",
            host="https://test.example.com",
            bearer_token="custom-secret-token"
        )

        call_args = mock_ws.connections.create.call_args
        options = call_args.kwargs["options"]
        assert options["bearer_token"] == "custom-secret-token"


class TestConnectionType:
    """Test connection type configuration."""

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_http_connection_type(self, mock_ws_class):
        """Connection type should be HTTP."""
        from scripts.create_agent_connection import create_a2a_connection
        from databricks.sdk.service.catalog import ConnectionType

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        create_a2a_connection(
            agent_name="test",
            host="https://test.example.com"
        )

        call_args = mock_ws.connections.create.call_args
        assert call_args.kwargs["connection_type"] == ConnectionType.HTTP


class TestConnectionComment:
    """Test connection comment/description."""

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_default_comment(self, mock_ws_class):
        """Default comment should include agent name."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        create_a2a_connection(
            agent_name="echo",
            host="https://test.example.com"
        )

        call_args = mock_ws.connections.create.call_args
        assert "echo" in call_args.kwargs["comment"]

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_custom_comment(self, mock_ws_class):
        """Custom comment should be used."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        mock_ws.connections.create.return_value = MockConnectionResponse()

        create_a2a_connection(
            agent_name="echo",
            host="https://test.example.com",
            comment="My custom echo agent"
        )

        call_args = mock_ws.connections.create.call_args
        assert call_args.kwargs["comment"] == "My custom echo agent"


class TestReturnValue:
    """Test function return value."""

    @patch('scripts.create_agent_connection.WorkspaceClient')
    def test_returns_connection_info(self, mock_ws_class):
        """Function should return connection info object."""
        from scripts.create_agent_connection import create_a2a_connection

        mock_ws = MagicMock()
        mock_ws_class.return_value = mock_ws
        expected_response = MockConnectionResponse(
            name="test-agent-a2a",
            full_name="catalog.schema.test-agent-a2a"
        )
        mock_ws.connections.create.return_value = expected_response

        result = create_a2a_connection(
            agent_name="test-agent",
            host="https://test.example.com"
        )

        assert result == expected_response
        assert result.name == "test-agent-a2a"
