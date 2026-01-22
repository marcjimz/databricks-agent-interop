"""Authorization for A2A Gateway using UC connection access.

Users must have access to the UC connection to use the corresponding agent.
Databricks Apps strip the Authorization header, so we use x-forwarded-email
to identify the user and check their grants on the connection.
"""

import logging
from typing import Optional
from fastapi import Request, HTTPException, status
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


class AuthService:
    """Handles authorization checks for A2A agent access."""

    def __init__(self, workspace_client: Optional[WorkspaceClient] = None):
        """Initialize authorization service.

        Args:
            workspace_client: Optional WorkspaceClient for testing.
        """
        self._client = workspace_client or WorkspaceClient()

    def get_user_email(self, request: Request) -> Optional[str]:
        """Extract user email from request headers.

        Databricks Apps provide user identity via x-forwarded-email header.
        For direct API calls, use the Authorization header token to identify the user.

        Args:
            request: The FastAPI request object.

        Returns:
            User email or None if not authenticated.
        """
        # Databricks Apps provide user identity via forwarded headers
        email = request.headers.get("x-forwarded-email")
        if email:
            return email

        # Direct API calls with Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                # Create a client with the user's token to get their identity
                user_client = WorkspaceClient(token=token)
                me = user_client.current_user.me()
                return me.user_name
            except Exception as e:
                logger.warning(f"Failed to identify user from token: {e}")

        return None

    def check_connection_access(
        self,
        connection_name: str,
        user_email: str
    ) -> bool:
        """Check if a user has USE_CONNECTION privilege on a connection.

        Args:
            connection_name: Name of the UC connection to check.
            user_email: Email of the user to check access for.

        Returns:
            True if user has USE_CONNECTION privilege, False otherwise.
        """
        # Check if user is the owner (owners always have access)
        try:
            connection = self._client.connections.get(connection_name)
            if connection and connection.owner == user_email:
                logger.debug(f"User {user_email} is owner of {connection_name}")
                return True
        except Exception as e:
            logger.warning(f"Error getting connection {connection_name}: {e}")
            return False

        # Check grants on the connection via REST API
        # (SDK grants.get doesn't support CONNECTION securable type)
        try:
            response = self._client.api_client.do(
                "GET",
                f"/api/2.1/unity-catalog/permissions/connection/{connection_name}"
            )

            # Check if user has USE_CONNECTION privilege
            if response and "privilege_assignments" in response:
                for assignment in response["privilege_assignments"]:
                    if assignment.get("principal") == user_email:
                        privileges = assignment.get("privileges", [])
                        if "USE_CONNECTION" in privileges:
                            logger.debug(f"User {user_email} has USE_CONNECTION on {connection_name}")
                            return True

            logger.info(f"User {user_email} lacks USE_CONNECTION on {connection_name}")
            return False

        except Exception as e:
            logger.warning(f"Error checking grants for {connection_name}: {e}")
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
        user_email = self.get_user_email(request)

        if not user_email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Unable to identify user."
            )

        if not self.check_connection_access(connection_name, user_email):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to agent connection: {connection_name}. "
                       f"Ensure you have USE_CONNECTION privilege."
            )


# Global authorization service instance
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get the global AuthService instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
