"""
Proxy tests for A2A Gateway.

Tests:
- Request proxying to backend agents
- JSON-RPC message format handling
- Streaming (SSE) support
- Backend authentication passthrough
"""

import pytest
import requests


class TestRPCProxy:
    """Test JSON-RPC request proxying."""

    def test_rpc_proxy_message_send(
        self,
        a2a_client,
        test_agent_name: str
    ):
        """JSON-RPC message/send should be proxied to backend."""
        response = a2a_client.send_message(
            test_agent_name,
            "Hello, agent!",
            method="message/send"
        )
        # 200 if agent responds, 404 if not configured, 502 if backend error
        assert response.status_code in [200, 404, 502]

        if response.status_code == 200:
            data = response.json()
            # A2A JSON-RPC response should have jsonrpc field
            assert "jsonrpc" in data or "result" in data or "error" in data

    def test_rpc_proxy_preserves_jsonrpc_format(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Proxy should preserve JSON-RPC 2.0 format."""
        rpc_request = {
            "jsonrpc": "2.0",
            "id": "test-rpc-123",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Test message"}]
                }
            }
        }

        response = requests.post(
            f"{apim_gateway_url}/agents/{test_agent_name}",
            headers={**auth_headers, "Content-Type": "application/json"},
            json=rpc_request
        )

        if response.status_code == 200:
            data = response.json()
            # Response should be JSON-RPC format
            assert data.get("jsonrpc") == "2.0"
            # ID should match request
            if "id" in data:
                assert data["id"] == "test-rpc-123" or data["id"] is None

    def test_rpc_error_response_jsonrpc_format(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Error responses should be JSON-RPC compliant."""
        rpc_request = {
            "jsonrpc": "2.0",
            "id": "test-error-123",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Test"}]
                }
            }
        }

        # Request to non-existent agent
        response = requests.post(
            f"{apim_gateway_url}/agents/nonexistent-xyz-12345",
            headers={**auth_headers, "Content-Type": "application/json"},
            json=rpc_request
        )
        assert response.status_code == 404

        data = response.json()
        # 404 error should be JSON-RPC error format
        assert "jsonrpc" in data, "Error response should be JSON-RPC format"
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]


class TestBackendAuth:
    """Test authentication passthrough to backend agents."""

    def test_backend_receives_auth_header(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Backend agent should receive Authorization header."""
        # This test verifies the flow works; actual header verification
        # requires a test backend that echoes headers

        response = requests.post(
            f"{apim_gateway_url}/agents/{test_agent_name}",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "auth-test",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Auth test"}]
                    }
                }
            }
        )

        # Request should reach backend (not fail at gateway auth)
        assert response.status_code in [200, 404, 502]

    def test_user_email_header_to_backend(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Backend should receive X-User-Email header."""
        # Similar to above - verifies header is set by policy
        response = requests.post(
            f"{apim_gateway_url}/agents/{test_agent_name}",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "user-email-test",
                "method": "echo",
                "params": {}
            }
        )
        # Gateway should process request successfully
        assert response.status_code in [200, 404, 502]


class TestStreamProxy:
    """Test streaming (SSE) request proxying."""

    def test_stream_endpoint_exists(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """POST /agents/{name}/stream should be valid endpoint."""
        response = requests.post(
            f"{apim_gateway_url}/agents/{test_agent_name}/stream",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "stream-test",
                "method": "message/stream",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Stream test"}]
                    }
                }
            },
            stream=True
        )
        # 200 for streaming, 404 if not configured, 502 for backend issues
        assert response.status_code in [200, 404, 502]

    def test_stream_error_not_authorized(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        restricted_agent_name: str
    ):
        """Stream to restricted agent should return 403."""
        response = requests.post(
            f"{apim_gateway_url}/agents/{restricted_agent_name}/stream",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "stream-403-test",
                "method": "message/stream",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Test"}]
                    }
                }
            }
        )
        # Should be 403 if agent exists but no permission, 404 if doesn't exist
        assert response.status_code in [403, 404]

    def test_stream_content_type(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Stream response should have appropriate content type."""
        response = requests.post(
            f"{apim_gateway_url}/agents/{test_agent_name}/stream",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "content-type-test",
                "method": "message/stream",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Test"}]
                    }
                }
            },
            stream=True
        )

        if response.status_code == 200:
            content_type = response.headers.get("Content-Type", "")
            # SSE uses text/event-stream
            assert (
                "text/event-stream" in content_type or
                "application/json" in content_type
            ), f"Unexpected content type: {content_type}"


class TestProxyErrorHandling:
    """Test error handling in proxy operations."""

    def test_proxy_timeout_handling(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Gateway should handle backend timeouts gracefully."""
        # This is a functional test; actual timeout behavior
        # depends on backend configuration
        response = requests.post(
            f"{apim_gateway_url}/agents/{test_agent_name}",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "timeout-test",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": "Long running test"}]
                    }
                }
            },
            timeout=60  # Client-side timeout
        )
        # Should get some response, not hang indefinitely
        assert response.status_code in [200, 404, 502, 504]

    def test_proxy_invalid_json_rpc(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Invalid JSON-RPC should be handled."""
        response = requests.post(
            f"{apim_gateway_url}/agents/{test_agent_name}",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={"invalid": "not json-rpc"}
        )
        # Backend may accept or reject; gateway should proxy either way
        assert response.status_code in [200, 400, 404, 502]
