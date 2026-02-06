"""
Unit tests for agent card generation script.

Tests:
- A2A-compliant agent card structure
- Security scheme generation
- UC connection parsing
"""

import pytest
from unittest.mock import Mock, patch


class MockConnection:
    """Mock Databricks connection object."""

    def __init__(
        self,
        name: str = "test-agent-a2a",
        full_name: str = "catalog.schema.test-agent-a2a",
        comment: str = "Test agent description",
        owner: str = "test-user@example.com",
        options: dict = None
    ):
        self.name = name
        self.full_name = full_name
        self.comment = comment
        self.owner = owner
        self.options = options or {
            "host": "https://test-backend.example.com",
            "base_path": "/a2a",
            "port": "443",
            "bearer_token": "databricks"
        }


class TestAgentCardStructure:
    """Test A2A-compliant agent card generation."""

    @patch('scripts.generate_agent_card.get_connection')
    def test_required_fields_present(self, mock_get_conn):
        """Agent card should have required A2A fields."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection()

        card = generate_agent_card("test-agent")

        # Required fields per A2A spec
        assert "name" in card
        assert "url" in card

    @patch('scripts.generate_agent_card.get_connection')
    def test_name_matches_agent(self, mock_get_conn):
        """Agent card name should match requested agent."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection(name="my-agent-a2a")

        card = generate_agent_card("my-agent")

        assert card["name"] == "my-agent"

    @patch('scripts.generate_agent_card.get_connection')
    def test_url_from_connection_options(self, mock_get_conn):
        """Agent URL should be built from connection options."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection(
            options={
                "host": "https://my-agent.example.com",
                "base_path": "/v1/agent"
            }
        )

        card = generate_agent_card("my-agent")

        assert card["url"] == "https://my-agent.example.com/v1/agent"

    @patch('scripts.generate_agent_card.get_connection')
    def test_description_from_comment(self, mock_get_conn):
        """Description should come from connection comment."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection(
            comment="My custom agent description"
        )

        card = generate_agent_card("test-agent")

        assert card["description"] == "My custom agent description"

    @patch('scripts.generate_agent_card.get_connection')
    def test_version_present(self, mock_get_conn):
        """Agent card should have version field."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection()

        card = generate_agent_card("test-agent")

        assert "version" in card
        assert card["version"]  # Not empty


class TestSecuritySchemes:
    """Test security scheme generation per A2A spec 4.5."""

    @patch('scripts.generate_agent_card.get_connection')
    def test_security_schemes_present(self, mock_get_conn):
        """Agent card should have securitySchemes."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection()

        card = generate_agent_card("test-agent")

        assert "securitySchemes" in card
        assert "bearer" in card["securitySchemes"]

    @patch('scripts.generate_agent_card.get_connection')
    def test_bearer_scheme_structure(self, mock_get_conn):
        """Bearer scheme should have correct structure."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection()

        card = generate_agent_card("test-agent")
        bearer = card["securitySchemes"]["bearer"]

        assert bearer["type"] == "http"
        assert bearer["scheme"] == "bearer"
        assert "bearerFormat" in bearer

    @patch('scripts.generate_agent_card.get_connection')
    def test_databricks_bearer_format(self, mock_get_conn):
        """Databricks auth should have specific bearer format."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection(
            options={"bearer_token": "databricks", "host": "https://test.com"}
        )

        card = generate_agent_card("test-agent")
        bearer = card["securitySchemes"]["bearer"]

        assert bearer["bearerFormat"] == "Databricks-JWT"
        assert "Databricks" in bearer["description"]

    @patch('scripts.generate_agent_card.get_connection')
    def test_generic_bearer_format(self, mock_get_conn):
        """Non-databricks auth should have generic bearer format."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection(
            options={"bearer_token": "some-token", "host": "https://test.com"}
        )

        card = generate_agent_card("test-agent")
        bearer = card["securitySchemes"]["bearer"]

        assert bearer["bearerFormat"] == "JWT"

    @patch('scripts.generate_agent_card.get_connection')
    def test_security_requirements_present(self, mock_get_conn):
        """Agent card should have security requirements."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection()

        card = generate_agent_card("test-agent")

        assert "security" in card
        assert isinstance(card["security"], list)
        assert len(card["security"]) > 0
        assert "bearer" in card["security"][0]


class TestCapabilities:
    """Test agent capabilities in card."""

    @patch('scripts.generate_agent_card.get_connection')
    def test_capabilities_present(self, mock_get_conn):
        """Agent card should declare capabilities."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection()

        card = generate_agent_card("test-agent")

        assert "capabilities" in card
        assert "streaming" in card["capabilities"]
        assert "pushNotifications" in card["capabilities"]

    @patch('scripts.generate_agent_card.get_connection')
    def test_input_output_modes(self, mock_get_conn):
        """Agent card should declare input/output modes."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection()

        card = generate_agent_card("test-agent")

        assert "defaultInputModes" in card
        assert "defaultOutputModes" in card
        assert "text" in card["defaultInputModes"]
        assert "text" in card["defaultOutputModes"]


class TestGatewayURL:
    """Test gateway URL handling."""

    @patch('scripts.generate_agent_card.get_connection')
    def test_gateway_url_override(self, mock_get_conn):
        """Gateway URL should override backend URL when provided."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection(
            options={"host": "https://backend.internal", "base_path": "/a2a"}
        )

        card = generate_agent_card(
            "test-agent",
            gateway_url="https://apim.example.com"
        )

        assert card["url"] == "https://apim.example.com/agents/test-agent"

    @patch('scripts.generate_agent_card.get_connection')
    def test_direct_url_without_gateway(self, mock_get_conn):
        """Without gateway URL, should use backend URL directly."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection(
            options={
                "host": "https://backend.internal",
                "base_path": "/a2a"
            }
        )

        card = generate_agent_card("test-agent")

        assert card["url"] == "https://backend.internal/a2a"


class TestUCConnectionExtension:
    """Test UC connection metadata extension."""

    @patch('scripts.generate_agent_card.get_connection')
    def test_uc_connection_extension(self, mock_get_conn):
        """Agent card should include UC connection extension."""
        from scripts.generate_agent_card import generate_agent_card

        mock_get_conn.return_value = MockConnection(
            name="my-agent-a2a",
            full_name="catalog.schema.my-agent-a2a"
        )

        card = generate_agent_card("my-agent")

        assert "_ucConnection" in card
        uc = card["_ucConnection"]
        assert uc["name"] == "my-agent-a2a"
        assert uc["fullName"] == "catalog.schema.my-agent-a2a"
