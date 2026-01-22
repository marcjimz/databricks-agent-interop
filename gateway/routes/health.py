"""Health and info endpoints for the A2A Gateway."""

from fastapi import APIRouter

from config import settings
from models import HealthResponse

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
