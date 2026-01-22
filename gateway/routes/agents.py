"""Agent discovery and proxy endpoints for the A2A Gateway.

Uses OBO (On-Behalf-Of) authentication to list and access agents
as the calling user, respecting Unity Catalog permissions.
"""

import logging

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from models import AgentListResponse, AgentInfo
from services import get_discovery, get_proxy_service, extract_token_from_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["Agents"])


@router.get("", response_model=AgentListResponse)
async def list_agents(request: Request):
    """List all discoverable A2A agents.

    Discovers agents by finding UC connections that end with '-a2a'.
    Uses OBO to list only connections the calling user has access to.
    """
    auth_token = extract_token_from_request(request)
    logger.info(f"list_agents: auth_token present={auth_token is not None}")

    discovery = get_discovery(auth_token=auth_token)
    agents = discovery.discover_agents()

    return AgentListResponse(
        agents=agents,
        total=len(agents)
    )


@router.get("/{agent_name}", response_model=AgentInfo)
async def get_agent(agent_name: str, request: Request):
    """Get information about a specific agent.

    Args:
        agent_name: Name of the agent (without -a2a suffix).
    """
    auth_token = extract_token_from_request(request)
    discovery = get_discovery(auth_token=auth_token)

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    return agent


@router.get("/{agent_name}/.well-known/agent.json")
async def get_agent_card(agent_name: str, request: Request):
    """Get the A2A agent card for a specific agent.

    Fetches from the agent_card_url stored in the UC connection.
    """
    auth_token = extract_token_from_request(request)
    discovery = get_discovery(auth_token=auth_token)
    proxy_service = get_proxy_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    return await proxy_service.fetch_agent_card(agent, request)


@router.post("/{agent_name}/message")
async def send_message(agent_name: str, request: Request):
    """Send a message to an A2A agent.

    Proxies the JSON-RPC request to the agent's endpoint URL (from agent card).
    """
    auth_token = extract_token_from_request(request)
    discovery = get_discovery(auth_token=auth_token)
    proxy_service = get_proxy_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    # Get request body
    body = await request.body()
    content_type = request.headers.get("content-type", "application/json")

    response = await proxy_service.send_message(agent, request, body, content_type)

    # Handle response
    try:
        content = response.json()
    except Exception:
        content = {"error": f"Invalid response from agent: {response.text[:500]}"}

    return JSONResponse(
        status_code=response.status_code,
        content=content
    )


@router.post("/{agent_name}/stream")
async def stream_message(agent_name: str, request: Request):
    """Send a streaming message to an A2A agent.

    Proxies the request and streams SSE responses back.
    """
    auth_token = extract_token_from_request(request)
    discovery = get_discovery(auth_token=auth_token)
    proxy_service = get_proxy_service()

    agent = discovery.get_agent_by_name(agent_name)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found"
        )

    body = await request.body()

    return StreamingResponse(
        proxy_service.stream_message(agent, request, body),
        media_type="text/event-stream"
    )
