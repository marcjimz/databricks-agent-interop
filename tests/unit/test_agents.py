"""Unit tests for individual A2A agents."""

import pytest
from tests.conftest import make_a2a_message


class TestEchoAgent:
    """Unit tests for the Echo Agent."""

    def test_echo_returns_input(self, http_client, echo_agent_url):
        """Test that echo agent echoes back the input message."""
        # Get endpoint from agent card
        card_resp = http_client.get(f"{echo_agent_url}/.well-known/agent.json")
        assert card_resp.status_code == 200
        card = card_resp.json()

        endpoint = card.get("url", "/")
        if endpoint.startswith("/"):
            endpoint = f"{echo_agent_url}{endpoint}"

        test_message = "Hello from unit test!"
        message = make_a2a_message(test_message)
        response = http_client.post(endpoint, json=message)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert "result" in data, f"Expected 'result' in response: {data}"

        # Verify the echo contains our message
        result_str = str(data["result"])
        assert "Hello" in result_str or "echo" in result_str.lower(), \
            f"Expected echo response to contain input: {result_str}"

    def test_echo_agent_card(self, http_client, echo_agent_url):
        """Test echo agent has valid agent card."""
        response = http_client.get(f"{echo_agent_url}/.well-known/agent.json")
        assert response.status_code == 200

        data = response.json()
        assert "name" in data
        assert "url" in data

    def test_echo_handles_special_characters(self, http_client, echo_agent_url):
        """Test echo agent handles special characters."""
        card_resp = http_client.get(f"{echo_agent_url}/.well-known/agent.json")
        card = card_resp.json()
        endpoint = card.get("url", "/")
        if endpoint.startswith("/"):
            endpoint = f"{echo_agent_url}{endpoint}"

        test_message = "Test @#$%^&*()"
        message = make_a2a_message(test_message)
        response = http_client.post(endpoint, json=message)

        assert response.status_code == 200
        data = response.json()
        assert "result" in data


class TestCalculatorAgent:
    """Unit tests for the Calculator Agent."""

    def _get_endpoint(self, http_client, calculator_agent_url):
        """Get calculator agent endpoint from agent card."""
        card_resp = http_client.get(f"{calculator_agent_url}/.well-known/agent.json")
        card = card_resp.json()
        endpoint = card.get("url", "/")
        if endpoint.startswith("/"):
            endpoint = f"{calculator_agent_url}{endpoint}"
        return endpoint

    def test_calculator_agent_card(self, http_client, calculator_agent_url):
        """Test calculator agent has valid agent card."""
        response = http_client.get(f"{calculator_agent_url}/.well-known/agent.json")
        assert response.status_code == 200

        data = response.json()
        assert "name" in data
        assert "url" in data

    def test_addition_2_plus_2_equals_4(self, http_client, calculator_agent_url):
        """Test that 2 + 2 = 4."""
        endpoint = self._get_endpoint(http_client, calculator_agent_url)
        message = make_a2a_message("add 2+2")
        response = http_client.post(endpoint, json=message)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert "result" in data, f"Expected 'result' in response: {data}"
        assert "4" in str(data["result"]), f"Expected result to contain '4': {data['result']}"

    def test_subtraction(self, http_client, calculator_agent_url):
        """Test subtraction: 10 - 3 = 7."""
        endpoint = self._get_endpoint(http_client, calculator_agent_url)
        message = make_a2a_message("subtract 3 from 10")
        response = http_client.post(endpoint, json=message)

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "7" in str(data["result"])

    def test_multiplication(self, http_client, calculator_agent_url):
        """Test multiplication: 6 * 7 = 42."""
        endpoint = self._get_endpoint(http_client, calculator_agent_url)
        message = make_a2a_message("multiply 6 by 7")
        response = http_client.post(endpoint, json=message)

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "42" in str(data["result"])

    def test_division(self, http_client, calculator_agent_url):
        """Test division: 20 / 4 = 5."""
        endpoint = self._get_endpoint(http_client, calculator_agent_url)
        message = make_a2a_message("divide 20 by 4")
        response = http_client.post(endpoint, json=message)

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "5" in str(data["result"])
