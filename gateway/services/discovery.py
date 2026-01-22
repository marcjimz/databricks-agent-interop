"""UC Connection-based agent discovery for A2A Gateway.

Discovers agents by finding Unity Catalog connections that end with '-a2a'.
Each connection's metadata contains the agent URL and capabilities.

Uses OBO (On-Behalf-Of) authentication when an auth token is provided,
allowing the gateway to list connections as the calling user.
"""

import logging
import os
from typing import List, Optional
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import ConnectionInfo

from config import settings
from models import AgentInfo, OAuthM2MCredentials

logger = logging.getLogger(__name__)


def extract_token_from_request(request) -> Optional[str]:
    """Extract bearer token from request Authorization header."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:]
    return None


def create_obo_client(auth_token: Optional[str] = None) -> WorkspaceClient:
    """Create a WorkspaceClient, optionally using OBO with the provided token.

    Args:
        auth_token: Optional bearer token for OBO authentication.
                   If provided, creates client as the token's user.
                   If None, uses app's default credentials.
    """
    if auth_token:
        host = os.environ.get("DATABRICKS_HOST", "")
        logger.info(f"Creating OBO client with token (length={len(auth_token)}) for host={host}")
        if host:
            return WorkspaceClient(token=auth_token, host=host)
        else:
            return WorkspaceClient(token=auth_token)
    else:
        logger.info("Creating client with app's default credentials (no OBO)")
        return WorkspaceClient()


class AgentDiscovery:
    """Discovers A2A agents via Unity Catalog connections."""

    def __init__(self, auth_token: Optional[str] = None):
        """Initialize discovery with optional auth token for OBO.

        Args:
            auth_token: Optional bearer token for OBO authentication.
                       If provided, UC connections are listed as that user.
        """
        self._auth_token = auth_token
        self._client: Optional[WorkspaceClient] = None

    @property
    def client(self) -> WorkspaceClient:
        """Get or create the workspace client."""
        if self._client is None:
            self._client = create_obo_client(self._auth_token)
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

        # Get agent card URL and auth from connection options
        options = conn.options or {}
        host = options.get("host", "")
        base_path = options.get("base_path", "")

        if not host:
            logger.warning(f"Connection {conn.name} has no host configured")
            return None

        if not base_path:
            logger.warning(f"Connection {conn.name} has no base_path configured")
            return None

        # Build agent card URL: host + base_path
        agent_card_url = host.rstrip("/") + base_path

        # Determine auth method from connection options
        bearer_token = None
        oauth_m2m = None

        raw_token = options.get("bearer_token", "")
        client_id = options.get("client_id")
        client_secret = options.get("client_secret")
        token_endpoint = options.get("token_endpoint")

        if client_id and client_secret and token_endpoint:
            # OAuth M2M credentials flow
            oauth_m2m = OAuthM2MCredentials(
                client_id=client_id,
                client_secret=client_secret,
                token_endpoint=token_endpoint,
                oauth_scope=options.get("oauth_scope")
            )
            logger.info(f"Connection {conn.name} configured with OAuth M2M")
        elif raw_token and raw_token.lower() == "databricks":
            # Same-tenant Databricks: pass through caller's Entra ID token
            bearer_token = None  # Signal for pass-through
            logger.debug(f"Connection {conn.name} configured for Databricks pass-through auth")
        elif raw_token and raw_token.lower() not in ("unused", "none", "placeholder", "oauth-passthrough"):
            # Static bearer token for external agents
            bearer_token = raw_token
            logger.debug(f"Connection {conn.name} configured with static bearer token")

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
            bearer_token=bearer_token,
            oauth_m2m=oauth_m2m,
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


def get_discovery(auth_token: Optional[str] = None) -> AgentDiscovery:
    """Get an AgentDiscovery instance.

    Args:
        auth_token: Optional bearer token for OBO authentication.
                   Each request should pass the user's token for proper OBO.

    Note: We create a new instance per request when auth_token is provided
    to ensure proper OBO isolation between users.
    """
    return AgentDiscovery(auth_token=auth_token)
