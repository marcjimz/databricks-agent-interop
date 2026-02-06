"""
Pytest configuration and fixtures for A2A Gateway tests.

Test organization:
- tests/unit/: Unit tests (mock external dependencies)
- tests/integration/: Integration tests (require live APIM gateway)

Environment variables for integration tests:
- APIM_GATEWAY_URL: Base URL of APIM gateway
- DATABRICKS_HOST: Databricks workspace URL
- DATABRICKS_TOKEN: Databricks OAuth token
- ENTRA_TOKEN: (Optional) Entra ID token for cross-platform tests
- TEST_AGENT_NAME: Agent with USE_CONNECTION permission (default: echo)
- RESTRICTED_AGENT_NAME: Agent without permission (default: restricted)

Run unit tests only:
    pytest tests/unit/

Run integration tests:
    APIM_GATEWAY_URL=https://... pytest tests/integration/

Run all tests with coverage:
    pytest --cov=scripts --cov-report=html
"""

import os
import sys
import pytest
import requests
from typing import Optional

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_env_or_skip(var_name: str) -> str:
    """Get environment variable or skip test if not set."""
    value = os.environ.get(var_name)
    if not value:
        pytest.skip(f"{var_name} not set")
    return value


@pytest.fixture(scope="session")
def apim_gateway_url() -> str:
    """APIM gateway base URL."""
    return get_env_or_skip("APIM_GATEWAY_URL")


@pytest.fixture(scope="session")
def databricks_host() -> str:
    """Databricks workspace URL."""
    return get_env_or_skip("DATABRICKS_HOST")


@pytest.fixture(scope="session")
def databricks_token() -> str:
    """Databricks OAuth token for testing."""
    return get_env_or_skip("DATABRICKS_TOKEN")


@pytest.fixture(scope="session")
def entra_token() -> Optional[str]:
    """Entra ID token for cross-platform testing (optional)."""
    return os.environ.get("ENTRA_TOKEN")


@pytest.fixture(scope="session")
def test_agent_name() -> str:
    """Name of the test agent (must have USE_CONNECTION granted)."""
    return os.environ.get("TEST_AGENT_NAME", "echo")


@pytest.fixture(scope="session")
def restricted_agent_name() -> str:
    """Name of agent without permission (for 403 tests)."""
    return os.environ.get("RESTRICTED_AGENT_NAME", "restricted")


@pytest.fixture
def auth_headers(databricks_token: str) -> dict:
    """Authorization headers with Databricks token."""
    return {"Authorization": f"Bearer {databricks_token}"}


@pytest.fixture
def entra_auth_headers(entra_token: Optional[str]) -> dict:
    """Authorization headers with Entra ID token."""
    if not entra_token:
        pytest.skip("ENTRA_TOKEN not set")
    return {"Authorization": f"Bearer {entra_token}"}


class A2AClient:
    """Helper client for A2A Gateway API calls."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    def list_agents(self) -> requests.Response:
        """List accessible agents."""
        return requests.get(
            f"{self.base_url}/agents",
            headers=self.headers
        )

    def get_agent(self, name: str) -> requests.Response:
        """Get agent info."""
        return requests.get(
            f"{self.base_url}/agents/{name}",
            headers=self.headers
        )

    def get_agent_card(self, name: str) -> requests.Response:
        """Get agent card."""
        return requests.get(
            f"{self.base_url}/agents/{name}/.well-known/agent.json",
            headers=self.headers
        )

    def send_message(self, name: str, message: str, method: str = "message/send") -> requests.Response:
        """Send A2A JSON-RPC message."""
        return requests.post(
            f"{self.base_url}/agents/{name}",
            headers={**self.headers, "Content-Type": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": "test-1",
                "method": method,
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"type": "text", "text": message}]
                    }
                }
            }
        )


@pytest.fixture
def a2a_client(apim_gateway_url: str, databricks_token: str) -> A2AClient:
    """A2A client using Databricks token."""
    return A2AClient(apim_gateway_url, databricks_token)


@pytest.fixture
def entra_a2a_client(apim_gateway_url: str, entra_token: Optional[str]) -> A2AClient:
    """A2A client using Entra ID token."""
    if not entra_token:
        pytest.skip("ENTRA_TOKEN not set")
    return A2AClient(apim_gateway_url, entra_token)
