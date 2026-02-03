import json
import logging
import uuid
from typing import Generator

import mlflow
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    create_text_output_item
)

# Enable MLflow autologging for full observability
mlflow.langchain.autolog()

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# System prompt for the A2A orchestrator
SYSTEM_PROMPT = """You are an A2A Orchestrator Agent that can discover and communicate with other A2A-compliant agents.

You have access to tools that let you:
1. Discover available agents via the A2A Gateway (use discover_agents)
2. Call any A2A agent to perform tasks (use call_agent with agent_name and message)

When a user asks you to do something:
1. First, use discover_agents to find what agents are available
2. Call the appropriate agent using the agent name and your message
3. Return the result to the user

Always discover agents first rather than assuming what's available. Be helpful and concise.

Example workflow:
- User: "Calculate 2 + 2"
- You: Call discover_agents to see available agents
- You: Call call_agent with agent_name="marcin-calculator" and message="Add 2 and 2"
- You: Return the result to the user
"""

import os

def _load_config():
    """Load configuration from environment variables at runtime.

    Called when agent is instantiated (at deployment time), not at import time.
    """
    return {
        "foundation_model_endpoint": os.environ.get("FOUNDATION_MODEL_ENDPOINT", "databricks-meta-llama-3-1-8b-instruct"),
        "temperature": float(os.environ.get("TEMPERATURE", "0.1")),
        "max_tokens": int(os.environ.get("MAX_TOKENS", "1000")),
        "gateway_url": os.environ.get("GATEWAY_URL", "")  # REQUIRED - no default
    }


class A2AOBOCallingAgent(ResponsesAgent):
    """
    Class representing a tool-calling Agent.
    Handles both tool execution via exec_fn and LLM interactions via model serving.
    """

    def __init__(self):
        """Initialize agent. Config will be loaded from environment variables at predict time."""
        logger.debug("=== __init__ called ===")
        # Enable OBO debug mode for troubleshooting authentication issues
        os.environ["OBO_DEBUG_MODE"] = "true"
        # Config is loaded lazily in predict() when env vars are available
        self._config_loaded = False
        self.endpoint = None
        self.temperature = None
        self.max_tokens = None
        self.gateway_url = None

    def _ensure_config(self):
        """Load config from environment variables on first predict call.

        Environment variables are set at deployment time via:
        agents.deploy(environment_vars={'GATEWAY_URL': '...', ...})
        """
        if self._config_loaded:
            return

        config = _load_config()
        self.endpoint = config.get("foundation_model_endpoint", "databricks-meta-llama-3-1-8b-instruct")
        self.temperature = config.get("temperature", 0.1)
        self.max_tokens = config.get("max_tokens", 1000)
        self.gateway_url = config.get("gateway_url", "")

        # Log config (don't validate here - let tools fail with clear errors if gateway_url missing)
        logger.info(f"Config loaded - Endpoint: {self.endpoint}, Gateway: {self.gateway_url or '(not set)'}")
        self._config_loaded = True

    def _create_tools(self, auth_headers: dict, gateway_url: str):
        """Create A2A tools with the provided auth headers.

        These tools use the OBO credentials from the calling user.
        """
        from langchain_core.tools import tool
        import httpx

        @tool
        def discover_agents() -> str:
            """Discover available A2A agents via the gateway.

            Returns a list of available agents with their names and descriptions.
            Use this when you need to know what agents are available.
            """
            try:
                with httpx.Client(timeout=30.0, headers=auth_headers) as client:
                    response = client.get(f"{gateway_url}/api/agents")
                    response.raise_for_status()
                    data = response.json()

                    agents_list = data.get("agents", [])
                    if not agents_list:
                        return "No agents found"

                    result = f"Found {len(agents_list)} agents:\n"
                    for agent in agents_list:
                        result += f"- {agent['name']}: {agent.get('description', 'No description')}\n"

                    return result
            except Exception as e:
                return f"Error discovering agents: {str(e)}"

        @tool
        def call_agent(agent_name: str, message: str) -> str:
            """Call an agent through the A2A Gateway by name.

            The gateway enforces UC connection access control.

            Args:
                agent_name: The short name of the agent (e.g., 'marcin-echo')
                message: The message to send

            Returns:
                The agent's response
            """
            headers = dict(auth_headers) if auth_headers else {}
            headers["Content-Type"] = "application/json"

            a2a_message = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": str(uuid.uuid4()),
                        "role": "user",
                        "parts": [{"kind": "text", "text": message}]
                    }
                }
            }

            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(
                        f"{gateway_url}/api/agents/{agent_name}/message",
                        json=a2a_message,
                        headers=headers
                    )
                    response.raise_for_status()
                    data = response.json()

                    # Extract result
                    result = data.get("result", {})
                    for artifact in result.get("artifacts", []):
                        for part in artifact.get("parts", []):
                            if part.get("kind") == "text":
                                return part.get("text", "")

                    return json.dumps(data)
            except Exception as e:
                return f"Error calling agent: {str(e)}"

        return [discover_agents, call_agent]

    def _extract_text_content(self, content) -> str:
        """Extract text from message content.

        Handles both string content and ResponseInputTextParam list format.

        Args:
            content: Either a string or a list of content items

        Returns:
            Extracted text as a string
        """
        if isinstance(content, str):
            return content

        # Handle list of content items (ResponseInputTextParam objects)
        if isinstance(content, list):
            text_parts = []
            for item in content:
                # Handle dict format
                if isinstance(item, dict):
                    if item.get("type") == "output_text" or item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                # Handle object format (ResponseInputTextParam)
                elif hasattr(item, "text"):
                    text_parts.append(item.text)
                elif hasattr(item, "content"):
                    text_parts.append(str(item.content))
            return "".join(text_parts)

        # Fallback to string conversion
        return str(content) if content else ""

    def _init_obo_and_agent(self, request: ResponsesAgentRequest):
        """Initialize OBO authentication, LLM, tools, and agent.

        Returns tuple of (agent, messages) ready for invoke/stream.
        """
        from databricks_langchain import ChatDatabricks
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        from langgraph.prebuilt import create_react_agent
        from databricks.sdk import WorkspaceClient
        from databricks_ai_bridge import ModelServingUserCredentials

        # Load config from environment variables on first call
        self._ensure_config()

        logger.debug("=== Initializing OBO ===")

        # Initialize OBO authentication - user identity is now known
        try:
            w = WorkspaceClient(credentials_strategy=ModelServingUserCredentials())
            auth_headers = dict(w.config.authenticate())
            logger.info("OBO authentication initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize OBO credentials: {type(e).__name__}: {e}")
            raise RuntimeError(
                f"OBO authentication failed: {e}. "
                "Ensure the model is deployed with OBO enabled and the user has appropriate permissions."
            ) from e

        # Initialize LLM
        llm = ChatDatabricks(
            endpoint=self.endpoint,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )

        # Create tools with OBO auth headers
        tools = self._create_tools(auth_headers, self.gateway_url)

        # Create the agent
        agent = create_react_agent(llm, tools)

        # Convert full conversation history to LangChain messages
        # ResponsesAgent content can be string or list of ResponseInputTextParam
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        for msg in request.input:
            text_content = self._extract_text_content(msg.content)
            if not text_content.strip():
                continue  # Skip empty messages

            if msg.role == "user":
                messages.append(HumanMessage(content=text_content))
            elif msg.role == "assistant":
                messages.append(AIMessage(content=text_content))

        return agent, messages

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        """Handle prediction requests in Agent Framework format.

        Supports full conversation history for multi-turn interactions.
        """
        agent, messages = self._init_obo_and_agent(request)

        # Invoke agent with full conversation history
        response = agent.invoke({"messages": messages})

        # Extract final message
        assistant_message = response["messages"][-1].content
        msg_id = str(uuid.uuid4())

        return ResponsesAgentResponse(
            output=[
                create_text_output_item(
                    text=assistant_message,
                    id=msg_id
                )
            ]
        )

    def predict_stream(
        self, request: ResponsesAgentRequest
    ) -> Generator[ResponsesAgentStreamEvent, None, None]:
        """Handle streaming prediction requests.

        Streams message updates as they become available from the LangGraph agent.
        """
        from langchain_core.messages import AIMessage

        agent, messages = self._init_obo_and_agent(request)

        item_id = str(uuid.uuid4())
        full_response = ""

        # Stream agent execution
        # create_react_agent streams chunks keyed by node name:
        # {"agent": {"messages": [...]}} or {"tools": {"messages": [...]}}
        for chunk in agent.stream({"messages": messages}):
            # Iterate through node outputs in the chunk
            for node_name, node_output in chunk.items():
                if "messages" not in node_output:
                    continue

                for msg in node_output["messages"]:
                    # Only stream assistant messages with non-empty content
                    if not isinstance(msg, AIMessage):
                        continue

                    content = getattr(msg, 'content', '')
                    if not content or not content.strip():
                        continue

                    # Add separator between multiple messages
                    if full_response:
                        full_response += "\n\n"
                        yield ResponsesAgentStreamEvent(
                            **self.create_text_delta(delta="\n\n", item_id=item_id)
                        )

                    # Update full response and yield delta
                    full_response += content
                    yield ResponsesAgentStreamEvent(
                        **self.create_text_delta(delta=content, item_id=item_id)
                    )

        # Final aggregation event with complete response
        yield ResponsesAgentStreamEvent(
            type="response.output_item.done",
            item=self.create_text_output_item(text=full_response, id=item_id)
        )


# Register the agent with MLflow
# Config validation is deferred to predict() when env vars are available
AGENT = A2AOBOCallingAgent()
mlflow.models.set_model(AGENT)