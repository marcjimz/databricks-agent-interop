"""Pytest configuration and shared fixtures for A2A Gateway tests."""

import os
import pytest
import httpx
from databricks.sdk import WorkspaceClient


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--gateway-url",
        action="store",
        default=os.environ.get("GATEWAY_URL"),
        help="A2A Gateway URL"
    )
    parser.addoption(
        "--echo-agent-url",
        action="store",
        default=os.environ.get("ECHO_AGENT_URL"),
        help="Echo Agent URL (direct)"
    )
    parser.addoption(
        "--calculator-agent-url",
        action="store",
        default=os.environ.get("CALCULATOR_AGENT_URL"),
        help="Calculator Agent URL (direct)"
    )
    parser.addoption(
        "--databricks-host",
        action="store",
        default=os.environ.get("DATABRICKS_HOST"),
        help="Databricks workspace host"
    )
    parser.addoption(
        "--prefix",
        action="store",
        default=os.environ.get("PREFIX", "marcin"),
        help="Resource prefix for connections"
    )


@pytest.fixture(scope="session")
def gateway_url(request):
    """Get the gateway URL from command line or environment."""
    url = request.config.getoption("--gateway-url")
    if not url:
        pytest.skip("Gateway URL not provided. Use --gateway-url or set GATEWAY_URL env var.")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def echo_agent_url(request):
    """Get the echo agent URL from command line or environment."""
    url = request.config.getoption("--echo-agent-url")
    if not url:
        pytest.skip("Echo Agent URL not provided. Use --echo-agent-url or set ECHO_AGENT_URL env var.")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def calculator_agent_url(request):
    """Get the calculator agent URL from command line or environment."""
    url = request.config.getoption("--calculator-agent-url")
    if not url:
        pytest.skip("Calculator Agent URL not provided. Use --calculator-agent-url or set CALCULATOR_AGENT_URL env var.")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def databricks_host(request):
    """Get the Databricks host from command line or environment."""
    host = request.config.getoption("--databricks-host")
    if not host:
        # Try to get from SDK
        try:
            client = WorkspaceClient()
            host = client.config.host
        except Exception:
            pytest.skip("Databricks host not provided. Use --databricks-host or set DATABRICKS_HOST env var.")
    return host.rstrip("/")


@pytest.fixture(scope="session")
def prefix(request):
    """Get the resource prefix from command line or environment."""
    return request.config.getoption("--prefix")


@pytest.fixture(scope="session")
def workspace_client():
    """Get a Databricks WorkspaceClient."""
    return WorkspaceClient()


@pytest.fixture(scope="session")
def auth_token(workspace_client):
    """Get an authentication token for API calls."""
    # Get token from the SDK
    if workspace_client.config.token:
        return workspace_client.config.token

    # Try OAuth token
    if hasattr(workspace_client.config, 'oauth_token') and workspace_client.config.oauth_token:
        token = workspace_client.config.oauth_token()
        if token and hasattr(token, 'access_token'):
            return token.access_token

    pytest.fail("Unable to acquire authentication token from Databricks SDK")


@pytest.fixture(scope="session")
def current_user(workspace_client):
    """Get the current user's email."""
    me = workspace_client.current_user.me()
    return me.user_name


@pytest.fixture(scope="session")
def http_client(auth_token):
    """Create an HTTP client with authentication."""
    return httpx.Client(
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=60.0
    )


@pytest.fixture(scope="session")
def async_http_client(auth_token):
    """Create an async HTTP client with authentication."""
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=60.0
    )


@pytest.fixture
def echo_connection_name(prefix):
    """Get the echo agent connection name."""
    return f"{prefix}-echo-a2a"


@pytest.fixture
def calculator_connection_name(prefix):
    """Get the calculator agent connection name."""
    return f"{prefix}-calculator-a2a"


def make_a2a_message(text: str, message_id: str = "test-msg-1") -> dict:
    """Create an A2A JSON-RPC message."""
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "user",
                "parts": [{"kind": "text", "text": text}]
            }
        }
    }
