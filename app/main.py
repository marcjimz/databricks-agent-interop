"""A2A Gateway - Main FastAPI Application.

This gateway provides:
- Agent discovery via UC connections ending with '-a2a'
- Authorization via UC connection access control
- Proxy to downstream A2A agents with SSE streaming support
"""

import logging
import time
import httpx
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from functools import lru_cache

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models import AgentListResponse, HealthResponse, ErrorResponse, AgentInfo
from discovery import get_discovery
from authorization import get_auth_service

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# HTTP client for proxying requests
_http_client: Optional[httpx.AsyncClient] = None

# Agent card cache (agent_card_url -> card data)
_agent_card_cache: Dict[str, Dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global _http_client

    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    _http_client = httpx.AsyncClient(timeout=60.0)

    yield

    logger.info("Shutting down...")
    if _http_client:
        await _http_client.aclose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="A2A Gateway for Databricks - Agent Discovery and Proxying",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_timing(request: Request, call_next):
    """Add request timing header."""
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    response.headers["X-Process-Time"] = f"{duration:.3f}s"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc) if settings.debug else None}
    )


# =============================================================================
# Agent Card Fetching
# =============================================================================

async def fetch_agent_card(agent_card_url: str) -> Dict[str, Any]:
    """Fetch and cache an agent card from its URL.

    Args:
        agent_card_url: URL to the agent card JSON.

    Returns:
        The agent card as a dictionary.
    """
    if agent_card_url in _agent_card_cache:
        return _agent_card_cache[agent_card_url]

    try:
        response = await _http_client.get(agent_card_url)
        response.raise_for_status()
        card = response.json()
        _agent_card_cache[agent_card_url] = card
        logger.info(f"Fetched agent card from {agent_card_url}")
        return card
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch agent card from {agent_card_url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch agent card: {str(e)}"
        )


async def get_agent_endpoint_url(agent: AgentInfo) -> str:
    """Get the endpoint URL for an agent by fetching its agent card.

    Args:
        agent: AgentInfo with agent_card_url.

    Returns:
        The endpoint URL from the agent card.
    """
    card = await fetch_agent_card(agent.agent_card_url)
    url = card.get("url", "")

    # Handle relative URLs - use agent card URL as base
    if url.startswith("/"):
        from urllib.parse import urlparse
        parsed = urlparse(agent.agent_card_url)
        url = f"{parsed.scheme}://{parsed.netloc}{url}"

    if not url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent card does not contain a URL"
        )

    return url


# =============================================================================
# Health & Info Endpoints
# =============================================================================

@app.get("/", tags=["Health"])
async def root():
    """Root endpoint with gateway info."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "healthy",
        "docs": "/docs",
        "agents": "/api/agents"
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="healthy", version=settings.app_version)


@app.get("/.well-known/agent.json", tags=["A2A"])
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


# =============================================================================
# Agent Discovery Endpoints
# =============================================================================

@app.get("/api/agents", response_model=AgentListResponse, tags=["Discovery"])
async def list_agents(request: Request):
    """List all discoverable A2A agents.

    Discovers agents by finding UC connections that end with '-a2a'.
    Returns only agents the calling user has access to.
    """
    discovery = get_discovery()
    auth_service = get_auth_service()

    all_agents = discovery.discover_agents()

    # Filter to only agents the user can access
    accessible_agents = []
    for agent in all_agents:
        try:
            await auth_service.authorize_agent_access(request, agent.connection_name)
            accessible_agents.append(agent)
        except HTTPException:
            # User doesn't have access to this agent
            logger.debug(f"User cannot access agent: {agent.name}")

    return AgentListResponse(
        agents=accessible_agents,
        total=len(accessible_agents)
    )


@app.get("/api/agents/{agent_name}", response_model=AgentInfo, tags=["Discovery"])
async def get_agent(agent_name: str, request: Request):
    """Get information about a specific agent.

    Args:
        agent_name: Name of the agent (without -a2a suffix).
    """
    discovery = get_discovery()
    auth_service = get_auth_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    # Check authorization
    await auth_service.authorize_agent_access(request, agent.connection_name)

    return agent


@app.get("/api/agents/{agent_name}/.well-known/agent.json", tags=["A2A"])
async def get_agent_card_endpoint(agent_name: str, request: Request):
    """Get the A2A agent card for a specific agent.

    Fetches from the agent_card_url stored in the UC connection.
    """
    discovery = get_discovery()
    auth_service = get_auth_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    await auth_service.authorize_agent_access(request, agent.connection_name)

    return await fetch_agent_card(agent.agent_card_url)


# =============================================================================
# Agent Proxy Endpoints
# =============================================================================

@app.post("/api/agents/{agent_name}/message", tags=["Proxy"])
async def send_message(agent_name: str, request: Request):
    """Send a message to an A2A agent.

    Proxies the JSON-RPC request to the agent's endpoint URL (from agent card).
    """
    discovery = get_discovery()
    auth_service = get_auth_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    await auth_service.authorize_agent_access(request, agent.connection_name)

    # Get endpoint URL from agent card
    agent_url = await get_agent_endpoint_url(agent)

    # Get request body
    body = await request.body()
    content_type = request.headers.get("content-type", "application/json")

    try:
        response = await _http_client.post(
            agent_url,
            content=body,
            headers={"Content-Type": content_type}
        )
        return JSONResponse(
            status_code=response.status_code,
            content=response.json()
        )
    except httpx.HTTPError as e:
        logger.error(f"Failed to send message to {agent_url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to communicate with agent: {str(e)}"
        )


@app.post("/api/agents/{agent_name}/stream", tags=["Proxy"])
async def stream_message(agent_name: str, request: Request):
    """Send a streaming message to an A2A agent.

    Proxies the request and streams SSE responses back.
    """
    discovery = get_discovery()
    auth_service = get_auth_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    await auth_service.authorize_agent_access(request, agent.connection_name)

    # Get endpoint URL from agent card
    agent_url = await get_agent_endpoint_url(agent)
    body = await request.body()

    async def stream_response():
        try:
            async with _http_client.stream(
                "POST",
                agent_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream"
                }
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk
        except httpx.HTTPError as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {{'error': '{str(e)}'}}\n\n".encode()

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream"
    )


# =============================================================================
# Local Development
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
