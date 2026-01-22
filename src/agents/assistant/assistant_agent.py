"""Assistant Agent - An interoperable A2A agent that discovers and uses other agents.

This agent demonstrates true A2A interoperability by:
1. Being discoverable via its agent card (/.well-known/agent.json)
2. Using the A2A SDK client to discover and call other agents
3. Acting as an orchestrator that routes requests to appropriate agents

The agent uses the official A2A SDK (A2ACardResolver, ClientFactory) for all
inter-agent communication, making it fully interoperable with any A2A-compliant agent.
"""

import os
import json
import httpx
from typing import AsyncGenerator, Literal, Optional
from uuid import uuid4
from pydantic import BaseModel
from langchain_core.tools import tool

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, Part, TextPart
from a2a.utils import new_agent_text_message, new_task

# A2A SDK Client imports for interoperability
from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.types import Message as A2AMessage, Part, TextPart


# Configuration
GATEWAY_URL = os.getenv("GATEWAY_URL", "")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "")
AGENT_PREFIX = os.getenv("AGENT_PREFIX", "marcin")


class ResponseFormat(BaseModel):
    """Response format for the assistant agent."""
    status: Literal["completed", "input_required", "error"] = "completed"
    message: str
    agents_used: list[str] = []


# =============================================================================
# A2A SDK-based Tools for Agent Interoperability
# =============================================================================

@tool
async def discover_agents_via_gateway() -> str:
    """Discover all available A2A agents via the gateway.

    Uses the gateway's /api/agents endpoint to list agents the user has access to.

    Returns:
        JSON string with list of available agents and their descriptions.
    """
    if not GATEWAY_URL:
        return json.dumps({"error": "Gateway URL not configured"})

    try:
        headers = {}
        if GATEWAY_TOKEN:
            headers["Authorization"] = f"Bearer {GATEWAY_TOKEN}"

        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            response = await client.get(f"{GATEWAY_URL}/api/agents")
            response.raise_for_status()
            data = response.json()

            agents = []
            for agent in data.get("agents", []):
                agents.append({
                    "name": agent.get("name"),
                    "description": agent.get("description"),
                    "connection_name": agent.get("connection_name")
                })

            return json.dumps({"agents": agents, "total": len(agents)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def get_agent_card(agent_url: str) -> str:
    """Fetch and parse an agent's A2A card using the official SDK.

    Uses A2ACardResolver to discover agent capabilities.

    Args:
        agent_url: The base URL of the A2A agent.

    Returns:
        JSON string with agent card details (name, description, skills, capabilities).
    """
    try:
        headers = {}
        if GATEWAY_TOKEN:
            headers["Authorization"] = f"Bearer {GATEWAY_TOKEN}"

        async with httpx.AsyncClient(headers=headers, timeout=30.0) as httpx_client:
            # Use A2A SDK to resolve the agent card
            resolver = A2ACardResolver(httpx_client=httpx_client, base_url=agent_url)
            card = await resolver.get_agent_card()

            return json.dumps({
                "name": card.name,
                "description": card.description,
                "version": card.version,
                "url": card.url,
                "capabilities": {
                    "streaming": card.capabilities.streaming if card.capabilities else False,
                    "pushNotifications": card.capabilities.push_notifications if card.capabilities else False
                } if card.capabilities else {},
                "skills": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "examples": s.examples
                    }
                    for s in (card.skills or [])
                ]
            })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def call_a2a_agent(agent_url: str, message: str) -> str:
    """Call any A2A-compliant agent using the official A2A SDK client.

    This tool enables true interoperability - it can communicate with any
    agent that implements the A2A protocol.

    Args:
        agent_url: The base URL of the A2A agent (e.g., https://agent.example.com)
        message: The message to send to the agent

    Returns:
        The agent's response as a string
    """
    try:
        headers = {}
        if GATEWAY_TOKEN:
            headers["Authorization"] = f"Bearer {GATEWAY_TOKEN}"

        async with httpx.AsyncClient(headers=headers, timeout=60.0) as httpx_client:
            # Step 1: Resolve card and fix URL
            resolver = A2ACardResolver(httpx_client=httpx_client, base_url=agent_url)
            card = await resolver.get_agent_card(http_kwargs={"headers": headers} if headers else None)
            if card.url and not card.url.startswith("http"):
                card.url = agent_url.rstrip("/") + "/" + card.url.lstrip("/")

            # Step 2: Create A2A client using ClientFactory
            config = ClientConfig(httpx_client=httpx_client)
            factory = ClientFactory(config=config)
            client = factory.create(card=card)

            # Step 3: Create Message object (new SDK API)
            msg = A2AMessage(
                messageId=str(uuid4()),
                role="user",
                parts=[Part(root=TextPart(text=message))]
            )

            # Step 4: Send message via A2A protocol - collect final task
            final_task = None
            async for event in client.send_message(msg):
                if isinstance(event, tuple):
                    task, update = event
                    final_task = task

            # Step 5: Extract text from task
            if final_task and final_task.artifacts:
                for artifact in final_task.artifacts:
                    for part in artifact.parts:
                        if hasattr(part, 'root') and hasattr(part.root, 'text'):
                            return json.dumps({
                                "agent": agent_url,
                                "response": part.root.text,
                                "success": True
                            })

            # Return error if no text response found
            return json.dumps({
                "agent": agent_url,
                "response": "No response",
                "success": False
            })

    except Exception as e:
        return json.dumps({
            "error": str(e),
            "agent_url": agent_url,
            "success": False
        })


@tool
async def call_agent_via_gateway(agent_name: str, message: str) -> str:
    """Call an agent through the A2A Gateway (with UC access control).

    Uses the gateway to proxy requests, which enforces Unity Catalog
    connection access control.

    Args:
        agent_name: Name of the agent (as registered in the gateway)
        message: The message to send to the agent

    Returns:
        The agent's response as a string
    """
    if not GATEWAY_URL:
        return json.dumps({"error": "Gateway URL not configured"})

    try:
        headers = {"Content-Type": "application/json"}
        if GATEWAY_TOKEN:
            headers["Authorization"] = f"Bearer {GATEWAY_TOKEN}"

        # Create A2A message
        a2a_message = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": str(uuid4()),
                    "role": "user",
                    "parts": [{"kind": "text", "text": message}]
                }
            }
        }

        async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
            response = await client.post(
                f"{GATEWAY_URL}/api/agents/{agent_name}/message",
                json=a2a_message
            )
            response.raise_for_status()
            result = response.json()

            # Extract text from response
            text_result = ""
            if "result" in result:
                res = result["result"]
                if "artifacts" in res:
                    for artifact in res["artifacts"]:
                        for part in artifact.get("parts", []):
                            if part.get("kind") == "text":
                                text_result += part.get("text", "")

            return json.dumps({
                "agent": agent_name,
                "response": text_result or str(result),
                "success": True
            })

    except Exception as e:
        return json.dumps({
            "error": str(e),
            "agent": agent_name,
            "success": False
        })


# =============================================================================
# Assistant Agent Implementation
# =============================================================================

class AssistantAgent:
    """Interoperable assistant agent that orchestrates other A2A agents.

    This agent:
    1. Is discoverable via its own agent card
    2. Can discover other agents via the gateway or direct A2A card resolution
    3. Uses the A2A SDK client to communicate with other agents
    4. Can route requests to appropriate agents based on capabilities
    """

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]
    SYSTEM_INSTRUCTION = """You are an interoperable AI assistant that can discover and coordinate other A2A agents.

You have access to these tools for agent interoperability:

1. discover_agents_via_gateway() - List all agents available through the gateway
2. get_agent_card(agent_url) - Fetch an agent's capabilities using the A2A SDK
3. call_a2a_agent(agent_url, message) - Call any A2A agent directly using the SDK
4. call_agent_via_gateway(agent_name, message) - Call an agent through the gateway

When a user asks you something:
1. First understand what they need
2. Discover available agents if needed
3. Determine which agent(s) can help
4. Call the appropriate agent(s) using the A2A SDK
5. Combine and summarize results

Known agents (when deployed):
- Echo Agent: Echoes back messages (good for testing connectivity)
- Calculator Agent: Performs arithmetic (add, subtract, multiply, divide)

Be helpful and explain your reasoning as you orchestrate agents."""

    def __init__(self):
        self.tools = [
            discover_agents_via_gateway,
            get_agent_card,
            call_a2a_agent,
            call_agent_via_gateway
        ]
        self.llm = None
        self.graph = None

        # Try to use Databricks LLM if available
        endpoint = os.getenv("DBX_LLM_ENDPOINT")
        if endpoint:
            try:
                from databricks_langchain import ChatDatabricks
                from langgraph.prebuilt import create_react_agent

                self.llm = ChatDatabricks(
                    endpoint=endpoint,
                    temperature=0.1,
                    max_tokens=1024,
                )
                self.graph = create_react_agent(
                    self.llm.bind_tools(self.tools),
                    tools=self.tools,
                    prompt=self.SYSTEM_INSTRUCTION,
                )
                print(f"Assistant Agent initialized with LLM: {endpoint}")
            except Exception as e:
                print(f"Could not initialize LLM, using rule-based fallback: {e}")
                self.llm = None
        else:
            print("No DBX_LLM_ENDPOINT configured, using rule-based assistant")

    async def process(self, query: str, context_id: str) -> AsyncGenerator[dict, None]:
        """Process a user request by orchestrating available agents.

        Args:
            query: The user's request.
            context_id: The conversation context ID.

        Yields:
            Response dictionaries with content and status.
        """
        # Try LLM-based processing first (full interoperability)
        if self.llm and self.graph:
            try:
                async for event in self.graph.astream(
                    {"messages": [{"role": "user", "content": query}]},
                    config={"configurable": {"thread_id": context_id}},
                ):
                    if "agent" in event:
                        messages = event["agent"].get("messages", [])
                        for msg in messages:
                            if hasattr(msg, "content") and msg.content:
                                yield {
                                    "content": msg.content,
                                    "is_task_complete": True,
                                    "require_user_input": False
                                }
                                return
            except Exception as e:
                print(f"LLM processing failed, falling back to rule-based: {e}")

        # Rule-based fallback for basic operations
        query_lower = query.lower()

        # Check for discovery requests
        if any(word in query_lower for word in ["discover", "list", "available", "agents", "what agents"]):
            result = await discover_agents_via_gateway.ainvoke({})
            agents_data = json.loads(result)

            if "error" in agents_data:
                yield {
                    "content": f"Error discovering agents: {agents_data['error']}",
                    "is_task_complete": True,
                    "require_user_input": False
                }
                return

            agents = agents_data.get("agents", [])
            response = f"I found {len(agents)} available agents:\n\n"
            for agent in agents:
                response += f"**{agent['name']}**: {agent.get('description', 'No description')}\n"

            yield {
                "content": response,
                "is_task_complete": True,
                "require_user_input": False
            }
            return

        # Check for calculation requests - route to calculator
        if any(word in query_lower for word in ["add", "subtract", "multiply", "divide", "calculate", "math", "plus", "minus", "times"]):
            calc_agent = f"{AGENT_PREFIX}-calculator"

            yield {
                "content": f"Routing to Calculator Agent via A2A gateway...",
                "is_task_complete": False,
                "require_user_input": False
            }

            result = await call_agent_via_gateway.ainvoke({
                "agent_name": calc_agent,
                "message": query
            })
            result_data = json.loads(result)

            if result_data.get("success"):
                yield {
                    "content": f"Calculator Agent: {result_data.get('response', 'No response')}",
                    "is_task_complete": True,
                    "require_user_input": False
                }
            else:
                yield {
                    "content": f"Error from Calculator Agent: {result_data.get('error', 'Unknown error')}",
                    "is_task_complete": True,
                    "require_user_input": False
                }
            return

        # Check for echo requests
        if any(word in query_lower for word in ["echo", "repeat", "say back"]):
            echo_agent = f"{AGENT_PREFIX}-echo"

            result = await call_agent_via_gateway.ainvoke({
                "agent_name": echo_agent,
                "message": query
            })
            result_data = json.loads(result)

            if result_data.get("success"):
                yield {
                    "content": f"Echo Agent: {result_data.get('response', 'No response')}",
                    "is_task_complete": True,
                    "require_user_input": False
                }
            else:
                yield {
                    "content": f"Error from Echo Agent: {result_data.get('error', 'Unknown error')}",
                    "is_task_complete": True,
                    "require_user_input": False
                }
            return

        # Default: show help
        yield {
            "content": (
                "I'm an interoperable A2A Assistant that can discover and coordinate other agents.\n\n"
                "**What I can do:**\n"
                "- **Discover agents** - 'What agents are available?'\n"
                "- **Calculate** - 'Add 5 and 3' or 'Multiply 7 by 8'\n"
                "- **Echo** - 'Echo hello world'\n"
                "- **Get agent info** - 'What can the calculator agent do?'\n\n"
                "I use the A2A SDK to communicate with other agents, making me fully interoperable "
                "with any A2A-compliant agent."
            ),
            "is_task_complete": False,
            "require_user_input": True
        }


class AssistantAgentExecutor(AgentExecutor):
    """A2A executor for the Assistant Agent."""

    def __init__(self):
        self.agent = AssistantAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue
    ) -> None:
        """Execute the assistant agent for an A2A request."""
        query = context.get_user_input()
        task = context.current_task or new_task(context.message)

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        async for item in self.agent.process(query, task.context_id):
            if item["require_user_input"]:
                await updater.update_status(
                    TaskState.input_required,
                    new_agent_text_message(
                        item["content"], task.context_id, task.id
                    ),
                    final=True,
                )
                break
            elif item["is_task_complete"]:
                await updater.add_artifact(
                    [Part(root=TextPart(text=item["content"]))],
                    name="assistant_response"
                )
                await updater.complete()
                break
            else:
                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(
                        item["content"], task.context_id, task.id
                    ),
                )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel the current execution."""
        pass


# =============================================================================
# A2A Application Builder
# =============================================================================

def build_assistant_agent_app():
    """Build the Assistant Agent A2A application.

    Creates an A2A-compliant server with:
    - Agent card at /.well-known/agent.json
    - JSON-RPC message endpoints
    - Streaming support
    """
    import httpx
    from a2a.server.apps import A2AStarletteApplication
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import (
        InMemoryTaskStore,
        InMemoryPushNotificationConfigStore,
        BasePushNotificationSender,
    )
    from a2a.types import AgentCapabilities, AgentCard, AgentSkill

    capabilities = AgentCapabilities(
        streaming=True,
        push_notifications=False
    )

    skills = [
        AgentSkill(
            id="discover",
            name="Agent Discovery",
            description="Discover available A2A agents via the gateway or direct card resolution",
            tags=["discovery", "agents", "list"],
            examples=[
                "What agents are available?",
                "List all agents",
                "Discover agents"
            ],
        ),
        AgentSkill(
            id="orchestrate",
            name="Agent Orchestration",
            description="Route requests to appropriate agents and combine results using the A2A SDK",
            tags=["orchestrate", "coordinate", "delegate", "interop"],
            examples=[
                "Calculate 5 + 3 for me",
                "Echo hello world",
                "Help me with math"
            ],
        ),
        AgentSkill(
            id="interop",
            name="A2A Interoperability",
            description="Communicate with any A2A-compliant agent using the official SDK",
            tags=["a2a", "interoperability", "sdk"],
            examples=[
                "Call the calculator agent",
                "What can agent X do?",
                "Send a message to the echo agent"
            ],
        ),
    ]

    agent_card = AgentCard(
        name="Assistant Agent",
        description="An interoperable orchestrator that discovers and coordinates other A2A agents using the official A2A SDK",
        url="/",
        version="1.0.0",
        default_input_modes=AssistantAgent.SUPPORTED_CONTENT_TYPES,
        default_output_modes=AssistantAgent.SUPPORTED_CONTENT_TYPES,
        capabilities=capabilities,
        skills=skills,
    )

    httpx_client = httpx.AsyncClient()
    push_store = InMemoryPushNotificationConfigStore()
    push_sender = BasePushNotificationSender(
        httpx_client=httpx_client,
        config_store=push_store
    )

    request_handler = DefaultRequestHandler(
        agent_executor=AssistantAgentExecutor(),
        task_store=InMemoryTaskStore(),
        push_config_store=push_store,
        push_sender=push_sender,
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler
    )
    app = server.build()

    # Add root GET endpoint for browser access
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def root(request):
        return JSONResponse({
            "name": agent_card.name,
            "version": agent_card.version,
            "description": agent_card.description,
            "agent_card": "/.well-known/agent.json",
            "interoperability": "Uses A2A SDK (A2ACardResolver, ClientFactory) for agent communication"
        })

    app.routes.insert(0, Route("/", root, methods=["GET"]))

    async def _close_httpx():
        await httpx_client.aclose()
    app.add_event_handler("shutdown", _close_httpx)

    return app


# Create the app for uvicorn
app = build_assistant_agent_app()
