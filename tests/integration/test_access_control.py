"""Integration tests for access control scenarios.

Tests that the gateway properly enforces USE_CONNECTION permission.
With OBO (On-Behalf-Of) authentication:

1. The gateway uses the caller's token via OBO
2. Discovery checks USE_CONNECTION for each connection - users only see accessible agents
3. Direct agent access returns 403 Forbidden if user lacks USE_CONNECTION
"""

import pytest
import time
from tests.conftest import make_a2a_message


class TestAccessControlWorkflow:
    """End-to-end access control workflow tests."""

    @pytest.fixture(autouse=True)
    def setup_connections(self, workspace_client, prefix, current_user):
        """Store connection names and user for all tests."""
        self.echo_conn = f"{prefix}-echo-a2a"
        self.calc_conn = f"{prefix}-calculator-a2a"
        self.user = current_user
        self.client = workspace_client

        # Determine which connections we can test (not owned by current user)
        self.testable_connections = []
        for conn_name in [self.echo_conn, self.calc_conn]:
            try:
                conn = self.client.connections.get(conn_name)
                if conn.owner != current_user:
                    self.testable_connections.append({
                        "name": conn_name,
                        "agent_name": conn_name.replace("-a2a", "").split("-", 1)[-1] if "-" in conn_name else conn_name.replace("-a2a", ""),
                        "owner": conn.owner
                    })
            except Exception:
                pass

    def _grant_access(self, connection_name: str):
        """Grant USE_CONNECTION to current user."""
        self.client.api_client.do(
            "PATCH",
            f"/api/2.1/unity-catalog/permissions/connection/{connection_name}",
            body={
                "changes": [{
                    "add": ["USE_CONNECTION"],
                    "principal": self.user
                }]
            }
        )
        time.sleep(1)

    def _revoke_access(self, connection_name: str):
        """Revoke USE_CONNECTION from current user."""
        self.client.api_client.do(
            "PATCH",
            f"/api/2.1/unity-catalog/permissions/connection/{connection_name}",
            body={
                "changes": [{
                    "remove": ["USE_CONNECTION"],
                    "principal": self.user
                }]
            }
        )
        time.sleep(1)

    def _check_grants(self, connection_name: str) -> bool:
        """Check if current user has USE_CONNECTION."""
        try:
            response = self.client.api_client.do(
                "GET",
                f"/api/2.1/unity-catalog/permissions/connection/{connection_name}"
            )
            if response and "privilege_assignments" in response:
                for assignment in response["privilege_assignments"]:
                    if assignment.get("principal") == self.user:
                        return "USE_CONNECTION" in assignment.get("privileges", [])
            return False
        except Exception:
            return False

    def test_access_control_full_workflow(self, http_client, gateway_url, prefix):
        """Test the complete access control workflow.

        NOTE: This test only works on connections where the current user
        is NOT the owner. Owners always have access regardless of grants.

        Without USE_CONNECTION, direct access returns 403 Forbidden.
        """
        if not self.testable_connections:
            pytest.skip(
                f"No testable connections found. User {self.user} is owner of all connections. "
                "Access control tests require connections owned by a different user."
            )

        # Use the first testable connection
        conn = self.testable_connections[0]
        conn_name = conn["name"]
        agent_name = f"{prefix}-calculator"  # Use full agent name with prefix
        endpoint = f"{gateway_url}/api/agents/{agent_name}/message"
        message = make_a2a_message("What is 1 + 1?")

        print(f"\n=== Testing access control on {conn_name} (owner: {conn['owner']}) ===")
        print(f"=== Current user: {self.user} ===")

        # Step 1: Revoke access
        print("=== Step 1: Revoking access ===")
        self._revoke_access(conn_name)
        assert not self._check_grants(conn_name), "Grant should be removed"

        # Step 2: Verify 403 Forbidden
        print("=== Step 2: Verifying 403 Forbidden ===")
        resp = http_client.post(endpoint, json=message)
        assert resp.status_code == 403, f"Expected 403 Forbidden, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "error" in data, "Response should have error field"
        assert "USE_CONNECTION" in data["error"], "Error should mention USE_CONNECTION"

        # Step 3: Grant access
        print("=== Step 3: Granting access ===")
        self._grant_access(conn_name)
        assert self._check_grants(conn_name), "Grant should be added"

        # Step 4: Verify access granted
        print("=== Step 4: Verifying access granted ===")
        resp = http_client.post(endpoint, json=message)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "result" in data, f"Expected result in response: {data}"

        # Step 5: Revoke access again
        print("=== Step 5: Revoking access again ===")
        self._revoke_access(conn_name)

        # Step 6: Verify 403 Forbidden again
        print("=== Step 6: Verifying 403 Forbidden again ===")
        resp = http_client.post(endpoint, json=message)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"

        # Cleanup: Restore access
        print("=== Cleanup: Restoring access ===")
        self._grant_access(conn_name)

        print("=== Access control workflow test PASSED ===")


class TestAccessDeniedResponse:
    """Tests for access denied error responses."""

    def test_403_forbidden_when_no_access(self, http_client, gateway_url, workspace_client, prefix, current_user):
        """Test that agents without access return 403 Forbidden.

        When user lacks USE_CONNECTION privilege, they get a clear 403 error
        explaining that they need USE_CONNECTION on the connection.

        NOTE: This test only works on connections where the current user
        is NOT the owner. Owners always have access regardless of grants.
        """
        # Find a connection we don't own
        connection_name = None
        agent_name = None
        for conn_suffix, agent_suffix in [("calculator-a2a", "calculator"), ("echo-a2a", "echo")]:
            try:
                conn = workspace_client.connections.get(f"{prefix}-{conn_suffix}")
                if conn.owner != current_user:
                    connection_name = f"{prefix}-{conn_suffix}"
                    agent_name = f"{prefix}-{agent_suffix}"
                    break
            except Exception:
                pass

        if not connection_name:
            pytest.skip(f"No testable connections found. User {current_user} owns all connections.")

        # Temporarily revoke access
        workspace_client.api_client.do(
            "PATCH",
            f"/api/2.1/unity-catalog/permissions/connection/{connection_name}",
            body={
                "changes": [{
                    "remove": ["USE_CONNECTION"],
                    "principal": current_user
                }]
            }
        )
        time.sleep(1)

        try:
            message = make_a2a_message("Test")
            response = http_client.post(
                f"{gateway_url}/api/agents/{agent_name}/message",
                json=message
            )

            # Expect 403 Forbidden with clear error message
            assert response.status_code == 403, f"Expected 403 Forbidden, got {response.status_code}"
            data = response.json()
            assert "error" in data
            assert "USE_CONNECTION" in data["error"]
            assert connection_name in data["error"]
        finally:
            # Restore access
            workspace_client.api_client.do(
                "PATCH",
                f"/api/2.1/unity-catalog/permissions/connection/{connection_name}",
                body={
                    "changes": [{
                        "add": ["USE_CONNECTION"],
                        "principal": current_user
                    }]
                }
            )


class TestAgentListFiltering:
    """Tests for agent list filtering based on access."""

    def test_agents_list_filters_by_access(self, http_client, gateway_url, workspace_client, prefix, current_user):
        """Test that /api/agents only returns accessible agents.

        NOTE: This test requires at least one connection where the user is NOT the owner.
        Owners always have access, so we can only test filtering on non-owned connections.
        """
        echo_conn = f"{prefix}-echo-a2a"
        calc_conn = f"{prefix}-calculator-a2a"

        # Check which connections we own
        owned_connections = []
        non_owned_connections = []
        for conn_name in [echo_conn, calc_conn]:
            try:
                conn = workspace_client.connections.get(conn_name)
                if conn.owner == current_user:
                    owned_connections.append(conn_name)
                else:
                    non_owned_connections.append(conn_name)
            except Exception:
                pass

        if not non_owned_connections:
            pytest.skip(f"No testable connections. User {current_user} owns all connections.")

        # Revoke access from non-owned connections
        for conn_name in non_owned_connections:
            workspace_client.api_client.do(
                "PATCH",
                f"/api/2.1/unity-catalog/permissions/connection/{conn_name}",
                body={"changes": [{"remove": ["USE_CONNECTION"], "principal": current_user}]}
            )
        time.sleep(1)

        try:
            response = http_client.get(f"{gateway_url}/api/agents")
            assert response.status_code == 200

            data = response.json()
            agent_names = [a["name"] for a in data["agents"]]

            # Owned connections should always be visible
            for conn_name in owned_connections:
                agent_name = conn_name.replace("-a2a", "")
                assert agent_name in agent_names, f"Owned agent {agent_name} should be in list: {agent_names}"

            # Non-owned connections without grants should NOT be visible
            for conn_name in non_owned_connections:
                agent_name = conn_name.replace("-a2a", "")
                assert agent_name not in agent_names, f"Non-owned agent {agent_name} should NOT be in list: {agent_names}"
        finally:
            # Restore access to non-owned connections
            for conn_name in non_owned_connections:
                workspace_client.api_client.do(
                    "PATCH",
                    f"/api/2.1/unity-catalog/permissions/connection/{conn_name}",
                    body={"changes": [{"add": ["USE_CONNECTION"], "principal": current_user}]}
                )
