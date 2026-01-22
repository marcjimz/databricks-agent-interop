"""
A2A Orchestrator Agent - MLflow PyFunc Model

This agent can discover and call other A2A-compliant agents via the A2A Gateway.
It uses OBO (On-Behalf-Of) authentication to act on behalf of the calling user,
enabling fine-grained access control via Unity Catalog.

CRITICAL: OBO must be initialized in predict(), not load_context(), because
the user identity is only known at runtime when a request is made.

It is designed to be deployed to Mosaic AI Framework using agents.deploy().
"""

import mlflow
import json
import logging
from typing import Any

# Enable MLflow autologging for full observability
mlflow.langchain.autolog()

# Configure logging for debugging
logging.basicConfig(level=logging.DEBUG)
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


class A2AOrchestratorAgent(mlflow.pyfunc.PythonModel):
    """
    MLflow PyFunc model that orchestrates A2A agents via the A2A Gateway.

    Uses OBO (On-Behalf-Of) authentication to:
    - Act on behalf of the calling user
    - Enable fine-grained access control via Unity Catalog
    - Pass user identity through to the A2A Gateway

    CRITICAL: OBO is initialized in predict(), not load_context(), because
    the user identity is only available at request time.

    This model can be deployed to Databricks Mosaic AI Framework using agents.deploy()
    and will be discoverable/callable via the Model Serving endpoint.
    """

    def load_context(self, context):
        """Initialize static configuration when the model is loaded.

        NOTE: Do NOT initialize OBO here - user identity is not known yet.
        OBO must be initialized in predict() at request time.
        """
        logger.debug("=== load_context called ===")

        # Get configuration
        model_config = context.model_config if hasattr(context, 'model_config') else {}
        self.endpoint = model_config.get("foundation_model_endpoint", "databricks-meta-llama-3-1-8b-instruct")
        self.temperature = model_config.get("temperature", 0.1)
        self.max_tokens = model_config.get("max_tokens", 1000)

        # Gateway URL from config
        self.gateway_url = model_config.get("gateway_url", "")

        logger.debug(f"Endpoint: {self.endpoint}")
        logger.debug(f"Gateway URL: {self.gateway_url}")
        logger.debug("Static config loaded - OBO will be initialized in predict()")

    def _create_tools(self, auth_headers: dict, gateway_url: str):
        """Create A2A tools with the provided auth headers.

        These tools use the OBO credentials from the calling user.
        """
        from langchain_core.tools import tool
        from uuid import uuid4
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

    def predict(self, context, model_input, params=None) -> dict:
        """Handle prediction requests in Agent Framework format.

        CRITICAL: OBO authentication is initialized HERE because the user
        identity is only known at request time, not at model load time.
        """
        from databricks_langchain import ChatDatabricks
        from langchain_core.messages import SystemMessage
        from langgraph.prebuilt import create_react_agent
        import pandas as pd

        logger.debug("=== predict called - initializing OBO ===")

        # Initialize OBO authentication - user identity is now known
        # This is the CRITICAL part: ModelServingUserCredentials extracts
        # the calling user's identity from the request context
        # Ref: https://docs.databricks.com/aws/en/generative-ai/agent-framework/agent-authentication
        from databricks.sdk import WorkspaceClient
        from databricks_ai_bridge import ModelServingUserCredentials

        try:
            # Create WorkspaceClient with OBO credentials
            # This uses the calling user's identity, not a service account
            w = WorkspaceClient(credentials_strategy=ModelServingUserCredentials())
            auth_headers = dict(w.config.authenticate())
            logger.debug("OBO authentication initialized successfully")
        except Exception as e:
            # Do NOT silently ignore auth failures - fail explicitly
            logger.error(f"Failed to initialize OBO credentials: {type(e).__name__}: {e}")
            raise RuntimeError(
                f"OBO authentication failed: {e}. "
                "Ensure the model is deployed with OBO enabled and the user has appropriate permissions."
            ) from e

        # Get gateway URL - try from config first, then environment
        import os
        gateway_url = self.gateway_url or os.environ.get("GATEWAY_URL", "")
        if not gateway_url:
            logger.error("No gateway URL configured!")
            raise ValueError(
                "No gateway URL configured. Set gateway_url in model_config or GATEWAY_URL environment variable."
            )

        # Initialize LLM
        llm = ChatDatabricks(
            endpoint=self.endpoint,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )

        # Create tools with OBO auth headers
        tools = self._create_tools(auth_headers, gateway_url)
        logger.debug(f"Created {len(tools)} tools with OBO credentials")

        # Create the agent
        agent = create_react_agent(llm, tools)

        # Extract query from input
        if isinstance(model_input, pd.DataFrame):
            if "messages" in model_input.columns:
                messages_data = model_input["messages"].iloc[0]
                if isinstance(messages_data, list) and len(messages_data) > 0:
                    query = messages_data[-1].get("content", "")
                else:
                    query = str(messages_data)
            else:
                query = str(model_input.iloc[0, 0])
        elif isinstance(model_input, dict):
            if "messages" in model_input:
                messages_input = model_input["messages"]
                query = messages_input[-1].get("content", "") if messages_input else ""
            elif "input" in model_input:
                query = model_input["input"]
            else:
                query = str(model_input)
        elif hasattr(model_input, 'messages'):
            if hasattr(model_input.messages, '__len__') and len(model_input.messages) > 0:
                query = model_input.messages[-1].content
            else:
                query = ""
        else:
            query = str(model_input)

        # Invoke agent
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            {"role": "user", "content": query}
        ]

        response = agent.invoke({"messages": messages})

        # Extract final message
        assistant_message = response["messages"][-1].content

        # Return in Agent Framework format
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": assistant_message
                    },
                    "finish_reason": "stop"
                }
            ]
        }


# Set the model for MLflow "models from code" pattern
mlflow.models.set_model(A2AOrchestratorAgent())
