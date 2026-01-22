"""A2A Protocol Compliance Tests.

Tests the gateway's compliance with the A2A protocol specification.
Reference: https://a2a-protocol.org/latest/specification/
"""

import pytest
from tests.conftest import make_a2a_message


class TestAgentCardCompliance:
    """Tests for A2A Agent Card compliance at /.well-known/agent.json."""

    def test_agent_card_endpoint_exists(self, http_client, gateway_url):
        """Test that agent card is served at /.well-known/agent.json."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        assert response.status_code == 200, f"Agent card endpoint should return 200, got {response.status_code}"

    def test_agent_card_is_valid_json(self, http_client, gateway_url):
        """Test that agent card returns valid JSON."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict), "Agent card should be a JSON object"

    def test_agent_card_has_required_name(self, http_client, gateway_url):
        """Test that agent card has required 'name' field."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "name" in data, "Agent card must have 'name' field"
        assert isinstance(data["name"], str), "'name' must be a string"
        assert len(data["name"]) > 0, "'name' must not be empty"

    def test_agent_card_has_required_url(self, http_client, gateway_url):
        """Test that agent card has required 'url' field."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "url" in data, "Agent card must have 'url' field"
        assert isinstance(data["url"], str), "'url' must be a string"

    def test_agent_card_has_protocol_versions(self, http_client, gateway_url):
        """Test that agent card has 'protocolVersions' for version negotiation."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "protocolVersions" in data, "Agent card must have 'protocolVersions' field"
        assert isinstance(data["protocolVersions"], list), "'protocolVersions' must be an array"
        assert len(data["protocolVersions"]) > 0, "'protocolVersions' must not be empty"

    def test_agent_card_has_capabilities(self, http_client, gateway_url):
        """Test that agent card has 'capabilities' object."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "capabilities" in data, "Agent card must have 'capabilities' field"
        assert isinstance(data["capabilities"], dict), "'capabilities' must be an object"

    def test_agent_card_capabilities_use_camel_case(self, http_client, gateway_url):
        """Test that capabilities use camelCase per A2A spec."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        capabilities = data.get("capabilities", {})

        # Check for camelCase keys
        if "streaming" in capabilities:
            assert isinstance(capabilities["streaming"], bool)
        if "pushNotifications" in capabilities:
            assert isinstance(capabilities["pushNotifications"], bool)

        # Ensure snake_case is NOT used
        assert "push_notifications" not in capabilities, \
            "Use 'pushNotifications' (camelCase), not 'push_notifications'"

    def test_agent_card_has_skills(self, http_client, gateway_url):
        """Test that agent card has 'skills' array."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "skills" in data, "Agent card must have 'skills' field"
        assert isinstance(data["skills"], list), "'skills' must be an array"

    def test_agent_card_skills_have_required_fields(self, http_client, gateway_url):
        """Test that each skill has required id, name, description."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        skills = data.get("skills", [])

        for i, skill in enumerate(skills):
            assert "id" in skill, f"Skill {i} must have 'id' field"
            assert "name" in skill, f"Skill {i} must have 'name' field"
            assert "description" in skill, f"Skill {i} must have 'description' field"

    def test_agent_card_has_security_schemes(self, http_client, gateway_url):
        """Test that agent card declares security schemes."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "securitySchemes" in data, "Agent card should have 'securitySchemes' field"
        assert isinstance(data["securitySchemes"], dict), "'securitySchemes' must be an object"

    def test_agent_card_has_input_output_modes(self, http_client, gateway_url):
        """Test that agent card declares supported input/output modes."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()

        # At least one of these should be present
        has_input_modes = "defaultInputModes" in data or "supportedInputModes" in data
        has_output_modes = "defaultOutputModes" in data or "supportedOutputModes" in data

        assert has_input_modes, "Agent card should declare input modes"
        assert has_output_modes, "Agent card should declare output modes"


class TestJsonRpcCompliance:
    """Tests for JSON-RPC 2.0 message format compliance."""

    def test_message_send_accepts_valid_jsonrpc(self, http_client, gateway_url, prefix):
        """Test that message/send accepts valid JSON-RPC 2.0 format."""
        # First get an accessible agent
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for JSON-RPC test")

        agent = agents[0]
        message = make_a2a_message("Hello A2A")

        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}/message",
            json=message
        )

        # Should not fail due to format issues
        assert response.status_code in [200, 202], \
            f"Valid JSON-RPC should be accepted, got {response.status_code}: {response.text}"

    def test_message_format_has_required_jsonrpc_fields(self):
        """Test that make_a2a_message creates spec-compliant messages."""
        message = make_a2a_message("Test message")

        # JSON-RPC 2.0 required fields
        assert message.get("jsonrpc") == "2.0", "Must have jsonrpc: '2.0'"
        assert "id" in message, "Must have 'id' field"
        assert "method" in message, "Must have 'method' field"
        assert message.get("method") == "message/send", "Method should be 'message/send'"

    def test_message_params_structure(self):
        """Test that message params follow A2A structure."""
        message = make_a2a_message("Test message")

        assert "params" in message, "Must have 'params' field"
        params = message["params"]

        assert "message" in params, "params must have 'message' field"
        msg = params["message"]

        assert "role" in msg, "message must have 'role' field"
        assert msg["role"] in ["user", "agent"], "role must be 'user' or 'agent'"
        assert "parts" in msg, "message must have 'parts' field"
        assert isinstance(msg["parts"], list), "parts must be an array"

    def test_message_has_messageid_for_sdk_compatibility(self):
        """Test that message includes messageId for a2a-sdk compatibility.

        Note: The a2a-sdk implementation requires messageId in messages,
        though the core A2A spec uses contextId/taskId for conversation tracking.
        """
        message = make_a2a_message("Test message")
        msg = message["params"]["message"]

        # a2a-sdk requires messageId
        assert "messageId" in msg, \
            "a2a-sdk implementations require 'messageId' field"

    def test_message_parts_are_valid(self):
        """Test that message parts follow TextPart structure."""
        message = make_a2a_message("Test message")
        parts = message["params"]["message"]["parts"]

        assert len(parts) > 0, "Must have at least one part"

        for part in parts:
            assert "kind" in part, "Each part must have 'kind' field"
            assert part["kind"] in ["text", "file", "data"], \
                f"kind must be 'text', 'file', or 'data', got '{part['kind']}'"

            if part["kind"] == "text":
                assert "text" in part, "TextPart must have 'text' field"

    def test_message_with_context_id(self):
        """Test that contextId can be included for multi-turn conversations."""
        message = make_a2a_message("Follow-up message", context_id="ctx-123")
        msg = message["params"]["message"]

        assert "contextId" in msg, "contextId should be included when provided"
        assert msg["contextId"] == "ctx-123"

    def test_message_with_task_id(self):
        """Test that taskId can be included for task follow-ups."""
        message = make_a2a_message("Task follow-up", task_id="task-456")
        msg = message["params"]["message"]

        assert "taskId" in msg, "taskId should be included when provided"
        assert msg["taskId"] == "task-456"


class TestJsonRpcResponse:
    """Tests for JSON-RPC response format compliance."""

    def test_response_has_jsonrpc_version(self, http_client, gateway_url):
        """Test that responses include jsonrpc version."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for response test")

        agent = agents[0]
        message = make_a2a_message("Test")

        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}/message",
            json=message
        )

        if response.status_code == 200:
            data = response.json()
            # JSON-RPC responses should have jsonrpc field
            if "jsonrpc" in data:
                assert data["jsonrpc"] == "2.0"

    def test_response_has_result_or_error(self, http_client, gateway_url):
        """Test that responses have either 'result' or 'error'."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for response test")

        agent = agents[0]
        message = make_a2a_message("Test")

        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}/message",
            json=message
        )

        if response.status_code == 200:
            data = response.json()
            # Per JSON-RPC 2.0, must have result XOR error
            has_result = "result" in data
            has_error = "error" in data
            assert has_result or has_error, \
                "JSON-RPC response must have 'result' or 'error'"


class TestTaskLifecycleCompliance:
    """Tests for A2A task lifecycle state compliance."""

    VALID_TASK_STATES = [
        "submitted",
        "working",
        "input-required",
        "completed",
        "failed",
        "cancelled",
        "rejected"
    ]

    def test_response_task_has_valid_state(self, http_client, gateway_url):
        """Test that task responses use valid A2A states."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for task state test")

        agent = agents[0]
        message = make_a2a_message("Test task state")

        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}/message",
            json=message
        )

        if response.status_code == 200:
            data = response.json()
            result = data.get("result", {})

            # Check for status - can be a string or an object with 'state' field
            if "status" in result:
                status = result["status"]
                # Handle both string status and object with state field
                if isinstance(status, dict):
                    state = status.get("state")
                else:
                    state = status

                if state:
                    assert state in self.VALID_TASK_STATES, \
                        f"Task state '{state}' is not a valid A2A state. " \
                        f"Valid states: {self.VALID_TASK_STATES}"


class TestStreamingCompliance:
    """Tests for SSE streaming compliance."""

    def test_stream_endpoint_exists(self, http_client, gateway_url):
        """Test that streaming endpoint is available."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for streaming test")

        agent = agents[0]

        # Check that the stream endpoint exists (even if we don't fully test SSE)
        # We use a minimal request to verify the endpoint
        message = make_a2a_message("Stream test")

        # The endpoint should exist and not return 404
        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}/stream",
            json=message,
            headers={"Accept": "text/event-stream"}
        )

        assert response.status_code != 404, \
            "Streaming endpoint /stream should exist"

    def test_stream_returns_event_stream_content_type(self, http_client, gateway_url):
        """Test that streaming returns correct content type."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for streaming test")

        agent = agents[0]
        message = make_a2a_message("Stream test")

        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}/stream",
            json=message,
            headers={"Accept": "text/event-stream"}
        )

        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            assert "text/event-stream" in content_type, \
                f"Streaming should return text/event-stream, got {content_type}"


class TestErrorResponseCompliance:
    """Tests for A2A error response compliance."""

    def test_not_found_returns_proper_error(self, http_client, gateway_url):
        """Test that 404 returns proper error structure."""
        response = http_client.get(f"{gateway_url}/api/agents/nonexistent-agent-xyz")
        assert response.status_code == 404

        data = response.json()
        assert "error" in data, "Error response should have 'error' field"

    def test_invalid_agent_message_returns_error(self, http_client, gateway_url):
        """Test that invalid requests return proper error structure."""
        response = http_client.post(
            f"{gateway_url}/api/agents/nonexistent-agent-xyz/message",
            json=make_a2a_message("Test")
        )
        assert response.status_code == 404

        data = response.json()
        assert "error" in data, "Error response should have 'error' field"
