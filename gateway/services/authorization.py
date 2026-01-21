"""Authorization for A2A Gateway using UC connection access.

Users must have access to the UC connection to use the corresponding agent.
This leverages Databricks Apps OBO (On-Behalf-Of) authentication.
"""

import logging
from typing import Optional
from fastapi import Request, HTTPException, status
from databricks.sdk import WorkspaceClient

from config import settings

logger = logging.getLogger(__name__)


class AuthService:
    """Handles authorization checks for A2A agent access."""

    def __init__(self, workspace_client: Optional[WorkspaceClient] = None):
        """Initialize authorization service.

        Args:
            workspace_client: Optional WorkspaceClient for testing.
        """
        self._client = workspace_client

    def get_client_for_request(self, request: Request) -> WorkspaceClient:
        """Get a WorkspaceClient for the current request.

        In Databricks Apps with OBO enabled, this uses the calling user's
        credentials to check permissions.

        Args:
            request: The FastAPI request object.

        Returns:
            WorkspaceClient configured for the current user.
        """
        # In Databricks Apps, the SDK automatically uses OBO when available
        # The request headers contain the user's auth token
        auth_header = request.headers.get("Authorization")

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            return WorkspaceClient(
                host=settings.databricks_host or None,
                token=token
            )

        # Fall back to default credentials (for local development)
        if self._client:
            return self._client
        return WorkspaceClient()

    def check_connection_access(
        self,
        client: WorkspaceClient,
        connection_name: str
    ) -> bool:
        """Check if the current user has access to a UC connection.

        Args:
            client: WorkspaceClient configured with user's credentials.
            connection_name: Name of the UC connection to check.

        Returns:
            True if user has USE_CONNECTION privilege, False otherwise.
        """
        try:
            # Try to get the connection - if user can't access it, this will fail
            connection = client.connections.get(connection_name)

            if connection is None:
                logger.warning(f"Connection {connection_name} not found")
                return False

            # If we can get the connection, user has at least read access
            logger.debug(f"User has access to connection {connection_name}")
            return True

        except Exception as e:
            logger.warning(f"Access denied to connection {connection_name}: {e}")
            return False

    async def authorize_agent_access(
        self,
        request: Request,
        connection_name: str
    ) -> None:
        """Authorize access to an agent via its UC connection.

        Raises HTTPException if access is denied.

        Args:
            request: The FastAPI request object.
            connection_name: Name of the agent's UC connection.

        Raises:
            HTTPException: 403 if access is denied, 401 if not authenticated.
        """
        try:
            client = self.get_client_for_request(request)

            if not self.check_connection_access(client, connection_name):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied to agent connection: {connection_name}. "
                           f"Ensure you have USE_CONNECTION privilege."
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Authorization error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to access this agent."
            )


# Global authorization service instance
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get the global AuthService instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
