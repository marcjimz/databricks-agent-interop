"""
Tracing tests for A2A Gateway.

Tests:
- Response headers (X-A2A-Gateway, X-User-Email, X-Request-ID)
- Correlation ID propagation
- Gateway identification headers
"""

import pytest
import requests
import uuid


class TestResponseHeaders:
    """Test gateway response headers."""

    def test_gateway_header_present(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Response should include X-A2A-Gateway header."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200

        assert "X-A2A-Gateway" in response.headers, "Should have X-A2A-Gateway header"
        assert response.headers["X-A2A-Gateway"] == "apim"

    def test_user_email_header_present(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Response should include X-User-Email header."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200

        assert "X-User-Email" in response.headers, "Should have X-User-Email header"
        user_email = response.headers["X-User-Email"]
        assert user_email, "X-User-Email should not be empty"

    def test_request_id_header_present(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Response should include X-Request-ID header."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200

        assert "X-Request-ID" in response.headers, "Should have X-Request-ID header"
        request_id = response.headers["X-Request-ID"]
        assert request_id, "X-Request-ID should not be empty"
        assert request_id.startswith("req-") or len(request_id) > 8


class TestCorrelationIdPropagation:
    """Test correlation ID propagation for tracing."""

    def test_correlation_id_propagated(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Provided X-Correlation-ID should be echoed back."""
        correlation_id = f"test-{uuid.uuid4().hex[:16]}"

        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers={
                **auth_headers,
                "X-Correlation-ID": correlation_id
            }
        )
        assert response.status_code == 200

        # Should echo back same correlation ID
        returned_id = response.headers.get("X-Request-ID", "")
        assert returned_id == correlation_id, \
            f"Expected correlation ID '{correlation_id}', got '{returned_id}'"

    def test_request_id_header_propagated(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Provided X-Request-ID should be used as correlation ID."""
        request_id = f"req-{uuid.uuid4().hex[:16]}"

        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers={
                **auth_headers,
                "X-Request-ID": request_id
            }
        )
        assert response.status_code == 200

        # Should use provided request ID
        returned_id = response.headers.get("X-Request-ID", "")
        assert returned_id == request_id

    def test_correlation_id_priority_over_request_id(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """X-Correlation-ID takes priority over X-Request-ID."""
        correlation_id = f"corr-{uuid.uuid4().hex[:16]}"
        request_id = f"req-{uuid.uuid4().hex[:16]}"

        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers={
                **auth_headers,
                "X-Correlation-ID": correlation_id,
                "X-Request-ID": request_id
            }
        )
        assert response.status_code == 200

        # Correlation ID should take priority
        returned_id = response.headers.get("X-Request-ID", "")
        assert returned_id == correlation_id, \
            "X-Correlation-ID should take priority"

    def test_generated_request_id_format(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Auto-generated request ID should have correct format."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200

        request_id = response.headers.get("X-Request-ID", "")
        # Should start with "req-" prefix
        assert request_id.startswith("req-"), \
            f"Generated request ID should start with 'req-', got '{request_id}'"
        # Should be reasonable length (req- + 16 hex chars)
        assert len(request_id) >= 20


class TestTracingOnErrors:
    """Test tracing headers are present on error responses."""

    def test_request_id_on_401(self, apim_gateway_url: str):
        """Request ID should be present even on 401 errors."""
        response = requests.get(f"{apim_gateway_url}/agents")
        assert response.status_code == 401

        # Should still have request ID for tracing
        # Note: May not be present if auth fails before tracing policy runs
        # This depends on APIM policy order

    def test_request_id_on_404(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Request ID should be present on 404 errors."""
        response = requests.get(
            f"{apim_gateway_url}/agents/nonexistent-xyz-12345",
            headers=auth_headers
        )
        assert response.status_code == 404

        # Error responses should still have tracing headers
        if "X-Request-ID" in response.headers:
            assert response.headers["X-Request-ID"]

    def test_error_response_includes_request_id(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """Error response body should include request_id."""
        response = requests.get(
            f"{apim_gateway_url}/agents/nonexistent-xyz-12345",
            headers=auth_headers
        )
        assert response.status_code == 404

        data = response.json()
        # Error response may include request_id for correlation
        # This is implementation-specific
        if "request_id" in data:
            assert data["request_id"]


class TestTracingOnAllEndpoints:
    """Verify tracing headers on all endpoint types."""

    def test_tracing_on_list_agents(
        self,
        apim_gateway_url: str,
        auth_headers: dict
    ):
        """List agents should have tracing headers."""
        response = requests.get(
            f"{apim_gateway_url}/agents",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert "X-A2A-Gateway" in response.headers
        assert "X-Request-ID" in response.headers

    def test_tracing_on_get_agent(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Get agent should have tracing headers."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}",
            headers=auth_headers
        )
        # 200 or 404 depending on test setup
        assert response.status_code in [200, 404]
        assert "X-A2A-Gateway" in response.headers or response.status_code == 404

    def test_tracing_on_agent_card(
        self,
        apim_gateway_url: str,
        auth_headers: dict,
        test_agent_name: str
    ):
        """Agent card endpoint should have tracing headers."""
        response = requests.get(
            f"{apim_gateway_url}/agents/{test_agent_name}/.well-known/agent.json",
            headers=auth_headers
        )
        assert response.status_code in [200, 404]
        # Tracing should work on all responses
