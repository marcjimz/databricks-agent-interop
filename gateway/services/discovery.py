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


class AccessDeniedException(Exception):
    """Raised when user lacks USE_CONNECTION permission on an agent."""

    def __init__(self, agent_name: str, connection_name: str):
        self.agent_name = agent_name
        self.connection_name = connection_name
        super().__init__(
            f"Access denied to agent '{agent_name}'. "
            f"Ensure you have USE_CONNECTION privilege on connection '{connection_name}'."
        )


def extract_token_from_request(request) -> Optional[str]:
    """Extract bearer token from request.

    Databricks Apps strip the Authorization header and provide the user's
    OAuth token via x-forwarded-access-token header instead. This function
    checks both headers, preferring x-forwarded-access-token for OBO.
    """
    # First check for Databricks Apps forwarded token (OBO)
    forwarded_token = request.headers.get("x-forwarded-access-token")
    if forwarded_token:
        return forwarded_token

    # Fall back to standard Authorization header
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:]
    return None


def extract_user_email_from_request(request) -> Optional[str]:
    """Extract user email from Databricks Apps forwarded headers.

    When running in Databricks Apps, the x-forwarded-email header contains
    the authenticated user's email, even when the Authorization header is stripped.
    """
    return request.headers.get("x-forwarded-email")


def create_obo_client(auth_token: Optional[str] = None) -> WorkspaceClient:
    """Create a WorkspaceClient, optionally using OBO with the provided token.

    Args:
        auth_token: Optional bearer token for OBO authentication.
                   If provided, creates client as the token's user.
                   If None, uses app's default credentials.
    """
    if auth_token:
        # Get host from environment or from default SDK config
        host = os.environ.get("DATABRICKS_HOST", "")

        if not host:
            # Try to get host from the default WorkspaceClient config
            # This works in Databricks Apps where the SDK auto-detects the workspace
            try:
                default_client = WorkspaceClient()
                host = default_client.config.host
                logger.info(f"Got host from default SDK config: {host}")
            except Exception as e:
                logger.warning(f"Could not get host from default config: {e}")

        logger.info(f"Creating OBO client with token (length={len(auth_token)}) for host={host}")
        if host:
            return WorkspaceClient(token=auth_token, host=host)
        else:
            # Fall back to letting SDK try to figure it out
            logger.warning("No host found, creating OBO client without explicit host")
            return WorkspaceClient(token=auth_token)
    else:
        logger.info("Creating client with app's default credentials (no OBO)")
        return WorkspaceClient()


class AgentDiscovery:
    """Discovers A2A agents via Unity Catalog connections."""

    def __init__(self, auth_token: Optional[str] = None, user_email: Optional[str] = None):
        """Initialize discovery with optional auth token or user email.

        Args:
            auth_token: Optional bearer token for OBO authentication.
                       If provided, creates client as the token's user.
            user_email: Optional user email from x-forwarded-email header.
                       Used for permission checking when token is not available.
        """
        self._auth_token = auth_token
        self._user_email = user_email
        self._client: Optional[WorkspaceClient] = None

    @property
    def client(self) -> WorkspaceClient:
        """Get or create the workspace client."""
        if self._client is None:
            self._client = create_obo_client(self._auth_token)
        return self._client

    def _get_effective_user_email(self) -> Optional[str]:
        """Get the effective user email for permission checking.

        Priority:
        1. User email from x-forwarded-email header (Databricks Apps)
        2. User from OBO token (if available)
        3. None (will use app's identity)
        """
        if self._user_email:
            return self._user_email

        # Try to get from OBO client
        try:
            current_user = self.client.current_user.me()
            return current_user.user_name
        except Exception as e:
            logger.warning(f"Could not get user from client: {e}")
            return None

    def _check_user_has_use_connection(self, connection_name: str) -> bool:
        """Check if the user has USE_CONNECTION privilege.

        Uses app credentials to check the specified user's permissions.

        Args:
            connection_name: Name of the UC connection to check.

        Returns:
            True if user has USE_CONNECTION or is owner, False otherwise.
        """
        try:
            user_email = self._get_effective_user_email()
            if not user_email:
                logger.error("No user email available for permission check")
                return False

            logger.info(f"Checking USE_CONNECTION for user: {user_email} on {connection_name}")

            # Get connection details using app credentials
            try:
                connection = self.client.connections.get(connection_name)
                if not connection:
                    logger.info(f"Connection {connection_name} not found")
                    return False
                logger.info(f"Connection {connection_name} owner: {connection.owner}")
            except Exception as e:
                logger.error(f"Could not get connection {connection_name}: {e}")
                return False

            # Owners always have access
            if connection.owner == user_email:
                logger.info(f"User {user_email} is owner of {connection_name} - ACCESS GRANTED")
                return True

            # Check grants via REST API using app credentials
            try:
                response = self.client.api_client.do(
                    "GET",
                    f"/api/2.1/unity-catalog/permissions/connection/{connection_name}"
                )
                logger.info(f"Grants response for {connection_name}: {response}")

                if response and "privilege_assignments" in response:
                    for assignment in response["privilege_assignments"]:
                        principal = assignment.get("principal", "")
                        privileges = assignment.get("privileges", [])

                        if principal == user_email and "USE_CONNECTION" in privileges:
                            logger.info(f"User {user_email} has USE_CONNECTION on {connection_name} - ACCESS GRANTED")
                            return True

            except Exception as e:
                logger.error(f"Error checking grants for {connection_name}: {e}")
                # If we can't check grants, deny access to be safe
                return False

            logger.info(f"User {user_email} lacks USE_CONNECTION on {connection_name} - ACCESS DENIED")
            return False

        except Exception as e:
            logger.error(f"Error in _check_user_has_use_connection for {connection_name}: {e}")
            return False

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
        """Discover all available A2A agents the user has access to.

        Filters connections by USE_CONNECTION privilege. Users only see
        agents they have permission to use.

        Returns:
            List of AgentInfo for agents the user can access.
        """
        connections = self.list_a2a_connections()
        logger.info(f"Found {len(connections)} total A2A connections")
        agents = []

        for conn in connections:
            # Filter by USE_CONNECTION permission
            has_access = self._check_user_has_use_connection(conn.name)
            logger.info(f"Connection {conn.name}: has_access={has_access}")
            if not has_access:
                logger.info(f"Filtering out {conn.name} - user lacks USE_CONNECTION")
                continue

            agent_info = self.connection_to_agent_info(conn)
            if agent_info:
                agents.append(agent_info)

        logger.info(f"Discovered {len(agents)} A2A agents (filtered by permissions)")
        return agents

    def get_agent_by_name(self, agent_name: str) -> Optional[AgentInfo]:
        """Get agent info by its name if user has access.

        Checks USE_CONNECTION permission before returning agent info.
        Raises AccessDeniedException if connection exists but user lacks permission.

        Args:
            agent_name: Name of the agent (without -a2a suffix).

        Returns:
            AgentInfo if found and user has access, None if agent doesn't exist.

        Raises:
            AccessDeniedException: If agent exists but user lacks USE_CONNECTION.
        """
        connection_name = f"{agent_name}{settings.a2a_connection_suffix}"

        # First check if the connection exists
        conn = self.get_connection(connection_name)
        if not conn:
            logger.debug(f"Connection {connection_name} not found")
            return None

        # Connection exists - now check permission
        if not self._check_user_has_use_connection(connection_name):
            logger.info(f"User lacks USE_CONNECTION for {connection_name}")
            raise AccessDeniedException(agent_name, connection_name)

        return self.connection_to_agent_info(conn)


def get_discovery(auth_token: Optional[str] = None, user_email: Optional[str] = None) -> AgentDiscovery:
    """Get an AgentDiscovery instance.

    Args:
        auth_token: Optional bearer token for OBO authentication.
        user_email: Optional user email from x-forwarded-email header.
                   Used for permission checking in Databricks Apps.

    Note: We create a new instance per request to ensure proper
    isolation between users.
    """
    return AgentDiscovery(auth_token=auth_token, user_email=user_email)
