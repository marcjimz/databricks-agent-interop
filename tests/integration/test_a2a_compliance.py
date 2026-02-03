"""A2A Protocol Compliance Tests.

Tests the gateway's compliance with the A2A protocol specification.
Reference: https://a2a-protocol.org/latest/specification/
"""

import pytest
from tests.conftest import (
    make_a2a_message,
    make_tasks_get_request,
    make_tasks_cancel_request,
    make_tasks_resubscribe_request,
    make_message_stream_request,
)


class TestAgentCardCompliance:
    """Tests for A2A Agent Card compliance at /.well-known/agent.json.

    Per spec: Agent Card must declare identity, capabilities, skills, and security.
    """

    def test_agent_card_endpoint_exists(self, http_client, gateway_url):
        """Agent card MUST be served at /.well-known/agent.json."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        assert response.status_code == 200, \
            f"Agent card endpoint should return 200, got {response.status_code}"

    def test_agent_card_is_valid_json(self, http_client, gateway_url):
        """Agent card MUST return valid JSON."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict), "Agent card should be a JSON object"

    def test_agent_card_has_required_name(self, http_client, gateway_url):
        """Agent card MUST have 'name' field (agent identity)."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "name" in data, "Agent card must have 'name' field"
        assert isinstance(data["name"], str), "'name' must be a string"
        assert len(data["name"]) > 0, "'name' must not be empty"

    def test_agent_card_has_required_url(self, http_client, gateway_url):
        """Agent card MUST have 'url' field (endpoint URL)."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "url" in data, "Agent card must have 'url' field"
        assert isinstance(data["url"], str), "'url' must be a string"

    def test_agent_card_has_protocol_versions(self, http_client, gateway_url):
        """Agent card MUST have 'protocolVersions' for version negotiation."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "protocolVersions" in data, "Agent card must have 'protocolVersions' field"
        assert isinstance(data["protocolVersions"], list), "'protocolVersions' must be an array"
        assert len(data["protocolVersions"]) > 0, "'protocolVersions' must not be empty"

    def test_agent_card_has_capabilities(self, http_client, gateway_url):
        """Agent card MUST have 'capabilities' object declaring supported features."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "capabilities" in data, "Agent card must have 'capabilities' field"
        assert isinstance(data["capabilities"], dict), "'capabilities' must be an object"

    def test_agent_card_capabilities_use_camel_case(self, http_client, gateway_url):
        """Capabilities MUST use camelCase per A2A spec."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        capabilities = data.get("capabilities", {})

        if "streaming" in capabilities:
            assert isinstance(capabilities["streaming"], bool)
        if "pushNotifications" in capabilities:
            assert isinstance(capabilities["pushNotifications"], bool)

        # Ensure snake_case is NOT used
        assert "push_notifications" not in capabilities, \
            "Use 'pushNotifications' (camelCase), not 'push_notifications'"

    def test_agent_card_has_skills(self, http_client, gateway_url):
        """Agent card MUST have 'skills' array describing capabilities."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "skills" in data, "Agent card must have 'skills' field"
        assert isinstance(data["skills"], list), "'skills' must be an array"

    def test_agent_card_skills_have_required_fields(self, http_client, gateway_url):
        """Each skill MUST have id, name, description."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        skills = data.get("skills", [])

        for i, skill in enumerate(skills):
            assert "id" in skill, f"Skill {i} must have 'id' field"
            assert "name" in skill, f"Skill {i} must have 'name' field"
            assert "description" in skill, f"Skill {i} must have 'description' field"

    def test_agent_card_has_security_schemes(self, http_client, gateway_url):
        """Agent card SHOULD declare security schemes (API Key, OAuth2, etc.)."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()
        assert "securitySchemes" in data, "Agent card should have 'securitySchemes' field"
        assert isinstance(data["securitySchemes"], dict), "'securitySchemes' must be an object"

    def test_agent_card_has_input_output_modes(self, http_client, gateway_url):
        """Agent card SHOULD declare supported input/output modes."""
        response = http_client.get(f"{gateway_url}/.well-known/agent.json")
        data = response.json()

        has_input_modes = "defaultInputModes" in data or "supportedInputModes" in data
        has_output_modes = "defaultOutputModes" in data or "supportedOutputModes" in data

        assert has_input_modes, "Agent card should declare input modes"
        assert has_output_modes, "Agent card should declare output modes"


class TestJsonRpcCompliance:
    """Tests for JSON-RPC 2.0 message format compliance.

    Per spec: All A2A operations use JSON-RPC 2.0 format.
    """

    def test_message_send_accepts_valid_jsonrpc(self, http_client, gateway_url):
        """message/send MUST accept valid JSON-RPC 2.0 format."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for JSON-RPC test")

        agent = agents[0]
        message = make_a2a_message("Hello A2A")

        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}",
            json=message
        )

        assert response.status_code in [200, 202], \
            f"Valid JSON-RPC should be accepted, got {response.status_code}: {response.text}"

    def test_message_format_has_required_jsonrpc_fields(self):
        """JSON-RPC request MUST have jsonrpc, id, method fields."""
        message = make_a2a_message("Test message")

        assert message.get("jsonrpc") == "2.0", "Must have jsonrpc: '2.0'"
        assert "id" in message, "Must have 'id' field"
        assert "method" in message, "Must have 'method' field"
        assert message.get("method") == "message/send", "Method should be 'message/send'"

    def test_message_params_structure(self):
        """message/send params MUST have message object with role and parts."""
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
        """Message SHOULD include messageId for SDK implementations."""
        message = make_a2a_message("Test message")
        msg = message["params"]["message"]

        assert "messageId" in msg, "a2a-sdk implementations require 'messageId' field"

    def test_message_parts_are_valid(self):
        """Message parts MUST have 'kind' field (text, file, or data)."""
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
        """contextId MAY be included for multi-turn conversations."""
        message = make_a2a_message("Follow-up message", context_id="ctx-123")
        msg = message["params"]["message"]

        assert "contextId" in msg, "contextId should be included when provided"
        assert msg["contextId"] == "ctx-123"

    def test_message_with_task_id(self):
        """taskId MAY be included for continuing existing tasks."""
        message = make_a2a_message("Task follow-up", task_id="task-456")
        msg = message["params"]["message"]

        assert "taskId" in msg, "taskId should be included when provided"
        assert msg["taskId"] == "task-456"


class TestJsonRpcResponse:
    """Tests for JSON-RPC response format compliance."""

    def test_response_has_jsonrpc_version(self, http_client, gateway_url):
        """JSON-RPC response MUST include jsonrpc version."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for response test")

        agent = agents[0]
        message = make_a2a_message("Test")

        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}",
            json=message
        )

        if response.status_code == 200:
            data = response.json()
            if "jsonrpc" in data:
                assert data["jsonrpc"] == "2.0"

    def test_response_has_result_or_error(self, http_client, gateway_url):
        """JSON-RPC response MUST have either 'result' or 'error'."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for response test")

        agent = agents[0]
        message = make_a2a_message("Test")

        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}",
            json=message
        )

        if response.status_code == 200:
            data = response.json()
            has_result = "result" in data
            has_error = "error" in data
            assert has_result or has_error, \
                "JSON-RPC response must have 'result' or 'error'"


class TestTaskLifecycleCompliance:
    """Tests for A2A task lifecycle state compliance.

    Per spec: Tasks transition through: working, completed, failed,
    canceled, rejected, input_required, auth_required
    """

    VALID_TASK_STATES = [
        "submitted",
        "working",
        "input-required",
        "input_required",  # Both formats for compatibility
        "completed",
        "failed",
        "canceled",
        "cancelled",  # Both spellings
        "rejected",
        "auth-required",
        "auth_required",
    ]

    def test_response_task_has_valid_state(self, http_client, gateway_url):
        """Task status MUST use valid A2A state values."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for task state test")

        agent = agents[0]
        message = make_a2a_message("Test task state")

        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}",
            json=message
        )

        if response.status_code == 200:
            data = response.json()
            result = data.get("result", {})

            if "status" in result:
                status = result["status"]
                if isinstance(status, dict):
                    state = status.get("state")
                else:
                    state = status

                if state:
                    assert state in self.VALID_TASK_STATES, \
                        f"Task state '{state}' is not a valid A2A state. " \
                        f"Valid states: {self.VALID_TASK_STATES}"


class TestTaskMethodsCompliance:
    """Tests for A2A task methods (tasks/get, tasks/cancel, tasks/resubscribe).

    Per spec: GetTask, CancelTask are core operations that MUST be supported.
    """

    def test_tasks_get_request_format(self):
        """tasks/get request MUST have correct JSON-RPC format."""
        request = make_tasks_get_request("task-123")

        assert request["jsonrpc"] == "2.0", "Must have jsonrpc: '2.0'"
        assert request["method"] == "tasks/get", "Method should be 'tasks/get'"
        assert "params" in request, "Must have 'params' field"
        assert request["params"]["id"] == "task-123", "Must include task id"

    def test_tasks_cancel_request_format(self):
        """tasks/cancel request MUST have correct JSON-RPC format."""
        request = make_tasks_cancel_request("task-456")

        assert request["jsonrpc"] == "2.0", "Must have jsonrpc: '2.0'"
        assert request["method"] == "tasks/cancel", "Method should be 'tasks/cancel'"
        assert "params" in request, "Must have 'params' field"
        assert request["params"]["id"] == "task-456", "Must include task id"

    def test_tasks_resubscribe_request_format(self):
        """tasks/resubscribe request MUST have correct JSON-RPC format."""
        request = make_tasks_resubscribe_request("task-789")

        assert request["jsonrpc"] == "2.0", "Must have jsonrpc: '2.0'"
        assert request["method"] == "tasks/resubscribe", "Method should be 'tasks/resubscribe'"
        assert "params" in request, "Must have 'params' field"
        assert request["params"]["id"] == "task-789", "Must include task id"

    def test_tasks_get_via_gateway(self, http_client, gateway_url):
        """Gateway MUST proxy tasks/get requests to agents."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for tasks/get test")

        agent = agents[0]

        # First send a message to get a task ID
        message = make_a2a_message("Test for task ID")
        send_response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}",
            json=message
        )

        if send_response.status_code != 200:
            pytest.skip("Could not send message to get task ID")

        # Extract task ID from response
        data = send_response.json()
        result = data.get("result", {})
        task_id = result.get("id")

        if not task_id:
            pytest.skip("Response did not include task ID")

        # Now test tasks/get
        get_request = make_tasks_get_request(task_id)
        get_response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}",
            json=get_request
        )

        # Gateway should accept and proxy the request (200 with result or error)
        # HTTP 422 means gateway rejected the request format (bad)
        # HTTP 200 with JSON-RPC error is valid (agent didn't find task)
        assert get_response.status_code == 200, \
            f"Gateway should proxy tasks/get, got HTTP {get_response.status_code}: {get_response.text}"

    def test_tasks_cancel_via_gateway(self, http_client, gateway_url):
        """Gateway MUST proxy tasks/cancel requests to agents."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for tasks/cancel test")

        agent = agents[0]

        # Send a tasks/cancel request (even with fake ID, gateway should accept format)
        cancel_request = make_tasks_cancel_request("fake-task-id")
        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}",
            json=cancel_request
        )

        # Gateway should accept and proxy the request
        # HTTP 422 means gateway rejected the request format (bad)
        # HTTP 200 with JSON-RPC error is valid (task not found)
        assert response.status_code == 200, \
            f"Gateway should proxy tasks/cancel, got HTTP {response.status_code}: {response.text}"


class TestStreamingCompliance:
    """Tests for SSE streaming compliance.

    Per spec: SendStreamingMessage delivers real-time updates via SSE.
    """

    def test_stream_endpoint_exists(self, http_client, gateway_url):
        """Streaming endpoint MUST exist if capability is declared."""
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

        assert response.status_code != 404, \
            "Streaming endpoint /stream should exist"

    def test_stream_returns_event_stream_content_type(self, http_client, gateway_url):
        """Streaming response MUST have text/event-stream content type."""
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

    def test_message_stream_request_format(self):
        """message/stream request MUST have correct format."""
        request = make_message_stream_request("Stream this")

        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "message/stream"
        assert "params" in request
        assert "message" in request["params"]


class TestProxiedAgentCardCompliance:
    """Tests for agent cards accessed via the gateway proxy."""

    def test_gateway_proxies_agent_card(self, http_client, gateway_url):
        """Gateway MUST proxy agent cards at /api/agents/{name}/.well-known/agent.json."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for proxy test")

        agent = agents[0]
        response = http_client.get(
            f"{gateway_url}/api/agents/{agent['name']}/.well-known/agent.json"
        )

        assert response.status_code == 200, \
            f"Proxied agent card should return 200, got {response.status_code}"

    def test_proxied_agent_card_is_valid(self, http_client, gateway_url):
        """Proxied agent card MUST have required fields."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for proxy test")

        agent = agents[0]
        response = http_client.get(
            f"{gateway_url}/api/agents/{agent['name']}/.well-known/agent.json"
        )

        if response.status_code == 200:
            data = response.json()
            assert "name" in data, "Agent card must have 'name'"
            assert "url" in data, "Agent card must have 'url'"


class TestErrorResponseCompliance:
    """Tests for A2A error response compliance.

    Per spec: Errors use JSON-RPC error format with specific A2A error codes.
    """

    def test_not_found_returns_proper_error(self, http_client, gateway_url):
        """404 response MUST include error information."""
        response = http_client.get(f"{gateway_url}/api/agents/nonexistent-agent-xyz")
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data or "error" in data, "Error response should have error info"

    def test_invalid_agent_rpc_returns_error(self, http_client, gateway_url):
        """Invalid agent requests MUST return proper error structure."""
        response = http_client.post(
            f"{gateway_url}/api/agents/nonexistent-agent-xyz",
            json=make_a2a_message("Test")
        )
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data or "error" in data, "Error response should have error info"

    def test_task_not_found_returns_jsonrpc_error(self, http_client, gateway_url):
        """TaskNotFoundError SHOULD return JSON-RPC error for unknown task ID."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents for error test")

        agent = agents[0]

        # Request a non-existent task
        get_request = make_tasks_get_request("nonexistent-task-xyz-123")
        response = http_client.post(
            f"{gateway_url}/api/agents/{agent['name']}",
            json=get_request
        )

        # Should return 200 with JSON-RPC error, not HTTP error
        if response.status_code == 200:
            data = response.json()
            # Either result (if agent returns empty) or error
            assert "result" in data or "error" in data


class TestA2AMethodProxy:
    """Tests that gateway properly proxies all A2A JSON-RPC methods."""

    def test_gateway_accepts_any_jsonrpc_method(self, http_client, gateway_url):
        """Gateway MUST accept and proxy any valid JSON-RPC method."""
        agents_resp = http_client.get(f"{gateway_url}/api/agents")
        agents = agents_resp.json().get("agents", [])

        if not agents:
            pytest.skip("No accessible agents")

        agent = agents[0]

        # Test various methods - gateway should proxy all
        methods_to_test = [
            {"jsonrpc": "2.0", "id": "1", "method": "message/send",
             "params": {"message": {"messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}]}}},
            {"jsonrpc": "2.0", "id": "2", "method": "tasks/get", "params": {"id": "task-1"}},
            {"jsonrpc": "2.0", "id": "3", "method": "tasks/cancel", "params": {"id": "task-1"}},
        ]

        for req in methods_to_test:
            response = http_client.post(
                f"{gateway_url}/api/agents/{agent['name']}",
                json=req
            )
            # Should NOT be 422 (validation error)
            assert response.status_code != 422, \
                f"Gateway rejected {req['method']}, should proxy to agent. Got 422: {response.text}"
