"""Health and info endpoints for the A2A Gateway."""

import os
from fastapi import APIRouter, Request

from config import settings
from models import HealthResponse
from services import extract_token_from_request

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


@router.get("/debug/obo")
async def debug_obo(request: Request):
    """Debug endpoint to check OBO authentication."""
    from databricks.sdk import WorkspaceClient

    auth_token = extract_token_from_request(request)
    result = {
        "token_present": auth_token is not None,
        "token_length": len(auth_token) if auth_token else 0,
        "DATABRICKS_HOST": os.environ.get("DATABRICKS_HOST", "NOT SET"),
    }

    # First check default SDK config
    try:
        default_client = WorkspaceClient()
        result["default_sdk_host"] = default_client.config.host
    except Exception as e:
        result["default_sdk_error"] = str(e)

    if auth_token:
        try:
            # Try OBO client
            host = os.environ.get("DATABRICKS_HOST", "")
            if not host:
                try:
                    default_client = WorkspaceClient()
                    host = default_client.config.host
                except:
                    pass

            result["obo_host_used"] = host

            if host:
                client = WorkspaceClient(token=auth_token, host=host)
            else:
                client = WorkspaceClient(token=auth_token)

            me = client.current_user.me()
            result["obo_user"] = me.user_name
            result["obo_success"] = True

            # Try listing connections
            try:
                connections = list(client.connections.list())
                a2a_conns = [c.name for c in connections if c.name and c.name.endswith("-a2a")]
                result["a2a_connections"] = a2a_conns
                result["total_connections"] = len(connections)
                result["connections_success"] = True
            except Exception as e:
                result["connections_error"] = str(e)
                result["connections_success"] = False

        except Exception as e:
            result["obo_error"] = str(e)
            result["obo_success"] = False

    return result


def _get_agent_card():
    """Build the gateway's agent card."""
    return {
        "name": settings.app_name,
        "description": "A2A Gateway that discovers and proxies to Databricks agents via UC connections",
        "url": "/",
        "version": settings.app_version,
        "protocolVersions": ["1.0"],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False
        },
        "securitySchemes": {
            "bearer": {
                "type": "http",
                "scheme": "bearer",
                "description": "Databricks OAuth token or service principal token"
            }
        },
        "defaultInputModes": ["text", "text/plain", "application/json"],
        "defaultOutputModes": ["text", "text/plain", "application/json"],
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


@router.get("/.well-known/agent.json")
async def gateway_agent_card():
    """Return the gateway's own agent card for A2A discovery."""
    return _get_agent_card()


@router.get("/.well-known/agent-card.json")
async def gateway_agent_card_alias():
    """Alias for agent card (A2A SDK compatibility)."""
    return _get_agent_card()
