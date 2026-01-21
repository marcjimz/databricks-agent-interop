"""UC Connection-based agent discovery for A2A Gateway.

Discovers agents by finding Unity Catalog connections that end with '-a2a'.
Each connection's metadata contains the agent URL and capabilities.
"""

import logging
from typing import List, Optional
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import ConnectionInfo

from config import settings
from models import AgentInfo

logger = logging.getLogger(__name__)


class AgentDiscovery:
    """Discovers A2A agents via Unity Catalog connections."""

    def __init__(self, workspace_client: Optional[WorkspaceClient] = None):
        """Initialize discovery with optional workspace client.

        Args:
            workspace_client: Optional WorkspaceClient. If not provided,
                            will be created using environment credentials.
        """
        self._client = workspace_client

    @property
    def client(self) -> WorkspaceClient:
        """Get or create the workspace client."""
        if self._client is None:
            self._client = WorkspaceClient()
        return self._client

    def list_a2a_connections(self) -> List[ConnectionInfo]:
        """List all UC connections that end with the A2A suffix.

        Returns:
            List of ConnectionInfo objects for A2A-enabled connections.
        """
        try:
            all_connections = list(self.client.connections.list())
            a2a_connections = [
                conn for conn in all_connections
                if conn.name and conn.name.endswith(settings.a2a_connection_suffix)
            ]
            logger.info(f"Found {len(a2a_connections)} A2A connections")
            return a2a_connections
        except Exception as e:
            logger.error(f"Failed to list connections: {e}")
            return []

    def get_connection(self, connection_name: str) -> Optional[ConnectionInfo]:
        """Get a specific UC connection by name.

        Args:
            connection_name: Full name of the connection.

        Returns:
            ConnectionInfo if found, None otherwise.
        """
        try:
            return self.client.connections.get(connection_name)
        except Exception as e:
            logger.error(f"Failed to get connection {connection_name}: {e}")
            return None

    def connection_to_agent_info(self, conn: ConnectionInfo) -> Optional[AgentInfo]:
        """Convert a UC connection to AgentInfo.

        The connection's URL should point to the agent card JSON.

        Args:
            conn: ConnectionInfo from Unity Catalog.

        Returns:
            AgentInfo if the connection has valid A2A metadata, None otherwise.
        """
        if not conn.name:
            return None

        # Extract agent name by removing the -a2a suffix
        agent_name = conn.name
        if agent_name.endswith(settings.a2a_connection_suffix):
            agent_name = agent_name[:-len(settings.a2a_connection_suffix)]

        # Get agent card URL from connection options
        options = conn.options or {}
        agent_card_url = options.get("url", options.get("host", ""))

        if not agent_card_url:
            logger.warning(f"Connection {conn.name} has no agent card URL configured")
            return None

        # Parse catalog.schema from full_name or use defaults
        catalog = settings.catalog_name
        schema_name = settings.schema_name
        if conn.full_name:
            parts = conn.full_name.split(".")
            if len(parts) >= 2:
                catalog = parts[0]
                schema_name = parts[1]

        return AgentInfo(
            name=agent_name,
            description=conn.comment,
            agent_card_url=agent_card_url,
            connection_name=conn.name,
            catalog=catalog,
            schema_name=schema_name
        )

    def discover_agents(self) -> List[AgentInfo]:
        """Discover all available A2A agents.

        Returns:
            List of AgentInfo for all discoverable agents.
        """
        connections = self.list_a2a_connections()
        agents = []

        for conn in connections:
            agent_info = self.connection_to_agent_info(conn)
            if agent_info:
                agents.append(agent_info)

        logger.info(f"Discovered {len(agents)} A2A agents")
        return agents

    def get_agent_by_name(self, agent_name: str) -> Optional[AgentInfo]:
        """Get agent info by its name.

        Args:
            agent_name: Name of the agent (without -a2a suffix).

        Returns:
            AgentInfo if found, None otherwise.
        """
        connection_name = f"{agent_name}{settings.a2a_connection_suffix}"
        conn = self.get_connection(connection_name)
        if conn:
            return self.connection_to_agent_info(conn)
        return None


# Global discovery instance
_discovery: Optional[AgentDiscovery] = None


def get_discovery() -> AgentDiscovery:
    """Get the global AgentDiscovery instance."""
    global _discovery
    if _discovery is None:
        _discovery = AgentDiscovery()
    return _discovery
