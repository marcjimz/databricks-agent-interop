"""Agent discovery and proxy endpoints for the A2A Gateway."""

import logging

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from models import AgentListResponse, AgentInfo
from services import get_discovery, get_auth_service, get_proxy_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["Agents"])


@router.get("", response_model=AgentListResponse)
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


@router.get("/{agent_name}", response_model=AgentInfo)
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


@router.get("/{agent_name}/.well-known/agent.json")
async def get_agent_card(agent_name: str, request: Request):
    """Get the A2A agent card for a specific agent.

    Fetches from the agent_card_url stored in the UC connection.
    """
    discovery = get_discovery()
    auth_service = get_auth_service()
    proxy_service = get_proxy_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    await auth_service.authorize_agent_access(request, agent.connection_name)

    return await proxy_service.fetch_agent_card(agent.agent_card_url)


@router.post("/{agent_name}/message")
async def send_message(agent_name: str, request: Request):
    """Send a message to an A2A agent.

    Proxies the JSON-RPC request to the agent's endpoint URL (from agent card).
    """
    discovery = get_discovery()
    auth_service = get_auth_service()
    proxy_service = get_proxy_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    await auth_service.authorize_agent_access(request, agent.connection_name)

    # Get request body
    body = await request.body()
    content_type = request.headers.get("content-type", "application/json")

    response = await proxy_service.send_message(agent, request, body, content_type)

    return JSONResponse(
        status_code=response.status_code,
        content=response.json()
    )


@router.post("/{agent_name}/stream")
async def stream_message(agent_name: str, request: Request):
    """Send a streaming message to an A2A agent.

    Proxies the request and streams SSE responses back.
    """
    discovery = get_discovery()
    auth_service = get_auth_service()
    proxy_service = get_proxy_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    await auth_service.authorize_agent_access(request, agent.connection_name)

    body = await request.body()

    return StreamingResponse(
        proxy_service.stream_message(agent, request, body),
        media_type="text/event-stream"
    )
