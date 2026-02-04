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
from services.tracing import get_tracer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["Agents"])


def _get_agent_or_raise(discovery, agent_name: str) -> AgentInfo:
    """Get agent by name, raising appropriate HTTP exceptions."""
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
    tracer = get_tracer()

    logger.info(f"list_agents: auth_token present={auth_token is not None}, user_email={user_email}")

    with tracer.trace_request(
        request_type="gateway",
        headers=dict(request.headers),
        span_name="gateway.list_agents"
    ) as span:
        discovery = get_discovery(auth_token=auth_token, user_email=user_email)
        agents = discovery.discover_agents()

        # Record output
        if span:
            span.set_outputs({"agent_count": len(agents), "agents": [a.name for a in agents]})

    return AgentListResponse(agents=agents, total=len(agents))


@router.get("/{agent_name}/.well-known/agent.json")
async def get_agent_card(agent_name: str, request: Request):
    """Get the A2A agent card for a specific agent."""
    auth_token = extract_token_from_request(request)
    user_email = extract_user_email_from_request(request)
    discovery = get_discovery(auth_token=auth_token, user_email=user_email)
    proxy_service = get_proxy_service()

    agent = _get_agent_or_raise(discovery, agent_name)
    return await proxy_service.fetch_agent_card(agent, request)


@router.get("/{agent_name}", response_model=AgentInfo)
async def get_agent(agent_name: str, request: Request):
    """Get information about a specific agent."""
    auth_token = extract_token_from_request(request)
    user_email = extract_user_email_from_request(request)
    discovery = get_discovery(auth_token=auth_token, user_email=user_email)
    return _get_agent_or_raise(discovery, agent_name)


# NOTE: More specific POST routes must come before the catch-all /{agent_name}


@router.post("/{agent_name}/stream")
async def stream_message(agent_name: str, request: Request, body: A2AJsonRpcRequest = None):
    """Stream an A2A message response via SSE."""
    auth_token = extract_token_from_request(request)
    user_email = extract_user_email_from_request(request)
    discovery = get_discovery(auth_token=auth_token, user_email=user_email)
    proxy_service = get_proxy_service()
    tracer = get_tracer()

    agent = _get_agent_or_raise(discovery, agent_name)

    if body:
        raw_body = json.dumps(body.model_dump()).encode()
    else:
        raw_body = await request.body()

    # Build agent tags for tracing
    agent_tags = tracer.build_agent_tags(
        name=agent.name,
        connection_id=agent.connection_name,
        url=agent.url,
        method="message_stream"
    )

    # Note: For streaming, we trace the start but the span completes
    # before the stream finishes. This is a limitation of the current design.
    with tracer.trace_request(
        request_type="agent_proxy",
        headers=dict(request.headers),
        agent_tags=agent_tags
    ) as span:
        # Record input for streaming request
        if span:
            try:
                import json as json_module
                span.set_inputs({"request": json_module.loads(raw_body.decode()), "streaming": True})
            except Exception:
                span.set_inputs({"request": raw_body.decode()[:1000], "streaming": True})
            span.set_outputs({"note": "Streaming response - output captured in stream"})

    return StreamingResponse(
        proxy_service.stream_message(agent, request, raw_body),
        media_type="text/event-stream"
    )


@router.post("/{agent_name}")
async def rpc_endpoint(agent_name: str, request: Request, body: A2AJsonRpcRequest = None):
    """A2A JSON-RPC endpoint for an agent.

    Proxies any A2A JSON-RPC request to the agent's endpoint URL.

    Supported methods:
    - `message/send` - Send a message
    - `tasks/get` - Get task status by ID
    - `tasks/cancel` - Cancel a running task
    - `tasks/resubscribe` - Resubscribe to task updates

    For streaming responses, use the /stream endpoint instead.
    """
    auth_token = extract_token_from_request(request)
    user_email = extract_user_email_from_request(request)
    discovery = get_discovery(auth_token=auth_token, user_email=user_email)
    proxy_service = get_proxy_service()
    tracer = get_tracer()

    agent = _get_agent_or_raise(discovery, agent_name)

    if body:
        raw_body = json.dumps(body.model_dump()).encode()
    else:
        raw_body = await request.body()

    # Determine A2A method from body
    method = "send_message"
    if body and body.method:
        method = body.method.replace("/", "_").replace("message_send", "send_message")

    # Build agent tags for tracing
    agent_tags = tracer.build_agent_tags(
        name=agent.name,
        connection_id=agent.connection_name,
        url=agent.url,
        method=method
    )

    content_type = request.headers.get("content-type", "application/json")

    # Trace the agent proxy call with inputs/outputs
    with tracer.trace_request(
        request_type="agent_proxy",
        headers=dict(request.headers),
        agent_tags=agent_tags
    ) as span:
        # Record input
        if span:
            try:
                import json as json_module
                span.set_inputs({"request": json_module.loads(raw_body.decode())})
            except Exception:
                span.set_inputs({"request": raw_body.decode()[:1000]})

        response = await proxy_service.send_message(agent, request, raw_body, content_type)

        # Record output
        if span:
            try:
                span.set_outputs({"response": response.json(), "status_code": response.status_code})
            except Exception:
                span.set_outputs({"response": response.text[:1000], "status_code": response.status_code})

    try:
        content = response.json()
    except Exception:
        content = {"error": f"Invalid response from agent: {response.text[:500]}"}

    return JSONResponse(
        status_code=response.status_code,
        content=content
    )
