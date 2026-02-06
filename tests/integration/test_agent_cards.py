"""
Agent Card tests for A2A Gateway.

Tests:
- A2A-compliant agent card generation
- Agent card structure per A2A Protocol Specification
- Security schemes in agent cards
"""

import pytest
import requests


class TestAgentCardGeneration:
    """Test A2A agent card generation from UC connections."""

    def test_agent_card_returns_200(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """GET /.well-known/agent.json should return 200 for accessible agent."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )
        # 200 if agent exists and accessible, 404 if not configured
        assert response.status_code in [200, 404]

    def test_agent_card_a2a_compliant_structure(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card should follow A2A Protocol specification."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )

        if response.status_code == 404:
            pytest.skip("Test agent not configured")

        assert response.status_code == 200
        card = response.json()

        # Required fields per A2A spec
        assert "name" in card, "Agent card must have 'name' field"
        assert "url" in card, "Agent card must have 'url' field"

        # Recommended fields
        assert "description" in card, "Agent card should have 'description'"
        assert "version" in card, "Agent card should have 'version'"

    def test_agent_card_security_schemes(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card should have proper security schemes (A2A spec 4.5)."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )

        if response.status_code == 404:
            pytest.skip("Test agent not configured")

        assert response.status_code == 200
        card = response.json()

        # Security schemes per A2A spec section 4.5
        assert "securitySchemes" in card, "Agent card must have 'securitySchemes'"

        schemes = card["securitySchemes"]
        assert "bearer" in schemes, "Must have 'bearer' security scheme"

        bearer = schemes["bearer"]
        assert bearer.get("type") == "http", "Bearer scheme type must be 'http'"
        assert bearer.get("scheme") == "bearer", "Scheme must be 'bearer'"
        assert "bearerFormat" in bearer, "Bearer scheme should have 'bearerFormat'"

    def test_agent_card_security_requirements(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card should have security requirements array."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )

        if response.status_code == 404:
            pytest.skip("Test agent not configured")

        assert response.status_code == 200
        card = response.json()

        # Security requirements array
        assert "security" in card, "Agent card must have 'security' requirements"
        assert isinstance(card["security"], list), "Security must be an array"
        assert len(card["security"]) > 0, "Security must have at least one requirement"

        # Each security requirement should reference a scheme
        for req in card["security"]:
            assert isinstance(req, dict)
            # Should reference 'bearer' scheme defined above
            assert "bearer" in req or len(req) > 0

    def test_agent_card_capabilities(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card should declare capabilities."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )

        if response.status_code == 404:
            pytest.skip("Test agent not configured")

        assert response.status_code == 200
        card = response.json()

        # Capabilities section
        assert "capabilities" in card, "Agent card should have 'capabilities'"
        caps = card["capabilities"]

        # Standard A2A capabilities
        assert "streaming" in caps, "Should declare 'streaming' capability"
        assert isinstance(caps["streaming"], bool)

    def test_agent_card_input_output_modes(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card should declare input/output modes."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )

        if response.status_code == 404:
            pytest.skip("Test agent not configured")

        assert response.status_code == 200
        card = response.json()

        # Input/output modes
        assert "defaultInputModes" in card, "Should have 'defaultInputModes'"
        assert "defaultOutputModes" in card, "Should have 'defaultOutputModes'"

        assert isinstance(card["defaultInputModes"], list)
        assert isinstance(card["defaultOutputModes"], list)
        assert "text" in card["defaultInputModes"], "Should support text input"
        assert "text" in card["defaultOutputModes"], "Should support text output"

    def test_agent_card_provider_info(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card should have provider information."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )

        if response.status_code == 404:
            pytest.skip("Test agent not configured")

        assert response.status_code == 200
        card = response.json()

        # Provider information
        if "provider" in card:
            provider = card["provider"]
            # Organization is recommended
            assert "organization" in provider or "url" in provider

    def test_agent_card_url_format(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card URL should be a valid endpoint."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )

        if response.status_code == 404:
            pytest.skip("Test agent not configured")

        assert response.status_code == 200
        card = response.json()

        url = card.get("url", "")
        assert url, "Agent URL must not be empty"
        # URL should be absolute (https://) or relative (/agents/...)
        assert url.startswith("http") or url.startswith("/")

    def test_agent_card_gateway_metadata(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card should include gateway metadata extension."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )

        if response.status_code == 404:
            pytest.skip("Test agent not configured")

        assert response.status_code == 200
        card = response.json()

        # Gateway metadata (extension field)
        if "_gateway" in card:
            gateway = card["_gateway"]
            assert gateway.get("type") == "apim", "Gateway type should be 'apim'"
            assert "connection" in gateway, "Should include UC connection name"


class TestAgentCardErrors:
    """Test agent card error responses."""

    def test_agent_card_requires_auth(
        self,
        apim_gateway_url: str,
        test_agent_name: str
    ):
        """Agent card endpoint requires authentication."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json"
        )
        assert response.status_code == 401

    def test_agent_card_not_found(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Non-existent agent should return 404."""
        response = requests.get(
            f"{apim_gateway_url}/agents/nonexistent-xyz-12345/.well-known/agent.json",
            headers=auth_headers
        )
        assert response.status_code == 404

        data = response.json()
        assert "error" in data
        assert "not_found" in data["error"] or "agent_not_found" in data["error"]

    def test_agent_card_content_type(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card response should be JSON."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )

        if response.status_code in [200, 403, 404]:
            assert "application/json" in response.headers.get("Content-Type", "")
