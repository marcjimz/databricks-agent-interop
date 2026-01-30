"""Agent discovery and proxy endpoints for the A2A Gateway.

Uses OBO (On-Behalf-Of) authentication to list and access agents
as the calling user, respecting Unity Catalog permissions.
"""

import json
import logging

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from models import AgentListResponse, AgentInfo, A2AJsonRpcRequest
from services import (
    get_discovery,
    get_proxy_service,
    extract_token_from_request,
    extract_user_email_from_request,
    AccessDeniedException,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["Agents"])


def _get_agent_or_raise(discovery, agent_name: str) -> AgentInfo:
    """Get agent by name, raising appropriate HTTP exceptions.

    Args:
        discovery: AgentDiscovery instance with user's OBO token.
        agent_name: Name of the agent to look up.

    Returns:
        AgentInfo if found and user has access.

    Raises:
        HTTPException: 404 if agent not found, 403 if access denied.
    """
    try:
        agent = discovery.get_agent_by_name(agent_name)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent '{agent_name}' not found"
            )
        return agent
    except AccessDeniedException as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.get("", response_model=AgentListResponse)
async def list_agents(request: Request):
    """List all discoverable A2A agents.

    Returns only agents where the calling user has USE_CONNECTION privilege
    on the corresponding Unity Catalog connection.
    """
    auth_token = extract_token_from_request(request)
    user_email = extract_user_email_from_request(request)

    logger.info(f"list_agents: auth_token present={auth_token is not None}, user_email={user_email}")

    discovery = get_discovery(auth_token=auth_token, user_email=user_email)
    agents = discovery.discover_agents()

    return AgentListResponse(agents=agents, total=len(agents))


@router.get("/{agent_name}", response_model=AgentInfo)
async def get_agent(agent_name: str, request: Request):
    """Get information about a specific agent.

    Args:
        agent_name: Name of the agent (without -a2a suffix).

    Returns:
        AgentInfo for the requested agent.

    Raises:
        404: Agent not found.
        403: User lacks USE_CONNECTION privilege.
    """
    auth_token = extract_token_from_request(request)
    user_email = extract_user_email_from_request(request)
    discovery = get_discovery(auth_token=auth_token, user_email=user_email)
    return _get_agent_or_raise(discovery, agent_name)


@router.get("/{agent_name}/.well-known/agent.json")
async def get_agent_card(agent_name: str, request: Request):
    """Get the A2A agent card for a specific agent.

    Fetches from the agent_card_url stored in the UC connection.

    Raises:
        404: Agent not found.
        403: User lacks USE_CONNECTION privilege.
    """
    auth_token = extract_token_from_request(request)
    user_email = extract_user_email_from_request(request)
    discovery = get_discovery(auth_token=auth_token, user_email=user_email)
    proxy_service = get_proxy_service()

    agent = _get_agent_or_raise(discovery, agent_name)
    return await proxy_service.fetch_agent_card(agent, request)


@router.post("/{agent_name}/message")
async def send_message(agent_name: str, request: Request, body: A2AJsonRpcRequest = None):
    """Send a message to an A2A agent.

    Proxies the JSON-RPC request to the agent's endpoint URL (from agent card).

    The request body should be a JSON-RPC 2.0 message in A2A format:
    ```json
    {
      "jsonrpc": "2.0",
      "id": "req-123",
      "method": "message/send",
      "params": {
        "message": {
          "messageId": "msg-456",
          "role": "user",
          "parts": [{"kind": "text", "text": "Your message here"}]
        }
      }
    }
    ```

    Raises:
        404: Agent not found.
        403: User lacks USE_CONNECTION privilege.
    """
    auth_token = extract_token_from_request(request)
    user_email = extract_user_email_from_request(request)
    discovery = get_discovery(auth_token=auth_token, user_email=user_email)
    proxy_service = get_proxy_service()

    agent = _get_agent_or_raise(discovery, agent_name)

    # Get request body - use the Pydantic model if provided, otherwise read raw body
    if body:
        raw_body = json.dumps(body.model_dump()).encode()
    else:
        raw_body = await request.body()

    content_type = request.headers.get("content-type", "application/json")

    response = await proxy_service.send_message(agent, request, raw_body, content_type)

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
async def stream_message(agent_name: str, request: Request, body: A2AJsonRpcRequest = None):
    """Send a streaming message to an A2A agent.

    Proxies the request and streams SSE responses back.

    The request body should be a JSON-RPC 2.0 message in A2A format:
    ```json
    {
      "jsonrpc": "2.0",
      "id": "req-123",
      "method": "message/send",
      "params": {
        "message": {
          "messageId": "msg-456",
          "role": "user",
          "parts": [{"kind": "text", "text": "Your message here"}]
        }
      }
    }
    ```

    Raises:
        404: Agent not found.
        403: User lacks USE_CONNECTION privilege.
    """
    auth_token = extract_token_from_request(request)
    user_email = extract_user_email_from_request(request)
    discovery = get_discovery(auth_token=auth_token, user_email=user_email)
    proxy_service = get_proxy_service()

    agent = _get_agent_or_raise(discovery, agent_name)

    # Get request body - use the Pydantic model if provided, otherwise read raw body
    if body:
        raw_body = json.dumps(body.model_dump()).encode()
    else:
        raw_body = await request.body()

    return StreamingResponse(
        proxy_service.stream_message(agent, request, raw_body),
        media_type="text/event-stream"
    )
