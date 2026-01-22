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
