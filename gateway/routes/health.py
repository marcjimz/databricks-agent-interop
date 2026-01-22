"""Health and info endpoints for the A2A Gateway."""

from fastapi import APIRouter, Request
from databricks.sdk import WorkspaceClient

from config import settings
from models import HealthResponse
from services import get_auth_service

router = APIRouter(tags=["Gateway"])


@router.get("/")
async def root():
    """Root endpoint with gateway info."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "healthy",
        "docs": "/docs",
        "agents": "/api/agents"
    }


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy", version=settings.app_version)


@router.get("/.well-known/agent.json")
async def gateway_agent_card():
    """Return the gateway's own agent card for A2A discovery."""
    return {
        "name": settings.app_name,
        "description": "A2A Gateway that discovers and proxies to Databricks agents via UC connections",
        "url": "/",
        "version": settings.app_version,
        "capabilities": {
            "streaming": True,
            "push_notifications": False
        },
        "skills": [
            {
                "id": "discover_agents",
                "name": "Agent Discovery",
                "description": "Discover available A2A agents via Unity Catalog connections",
                "tags": ["discovery", "agents"],
                "examples": ["List all available agents", "Find agents"]
            },
            {
                "id": "proxy_agent",
                "name": "Agent Proxy",
                "description": "Proxy requests to discovered A2A agents",
                "tags": ["proxy", "routing"],
                "examples": ["Send message to agent X"]
            }
        ]
    }


@router.get("/debug/auth/{connection_name}")
async def debug_auth(connection_name: str, request: Request):
    """Debug endpoint to check authorization."""
    auth_service = get_auth_service()

    # Get user email from request
    user_email = auth_service.get_user_email(request)

    # Try to get grants directly
    client = WorkspaceClient()

    result = {
        "user_email_detected": user_email,
        "x_forwarded_email": request.headers.get("x-forwarded-email"),
        "has_auth_header": request.headers.get("Authorization") is not None,
        "connection_name": connection_name,
    }

    try:
        connection = client.connections.get(connection_name)
        result["connection_owner"] = connection.owner
        result["is_owner"] = connection.owner == user_email
    except Exception as e:
        result["connection_error"] = str(e)

    try:
        # Use REST API since SDK doesn't support CONNECTION securable type
        grants = client.api_client.do(
            "GET",
            f"/api/2.1/unity-catalog/permissions/connection/{connection_name}"
        )
        result["grants_raw"] = grants
        if grants and "privilege_assignments" in grants:
            result["privilege_assignments"] = []
            for assignment in grants["privilege_assignments"]:
                priv_info = {
                    "principal": assignment.get("principal"),
                    "principal_matches_user": assignment.get("principal") == user_email,
                    "privileges": assignment.get("privileges", []),
                    "has_use_connection": "USE_CONNECTION" in assignment.get("privileges", []),
                }
                result["privilege_assignments"].append(priv_info)
    except Exception as e:
        result["grants_error"] = str(e)

    return result
