"""
A2A Orchestrator Agent - MLflow PyFunc Model

This agent can discover and call other A2A-compliant agents using the official A2A SDK.
It is designed to be deployed to Mosaic AI Framework using agents.deploy().
"""

import mlflow
import json
import asyncio
from typing import Any

# System prompt for the A2A orchestrator
SYSTEM_PROMPT = """You are an A2A Orchestrator Agent that can discover and communicate with other A2A-compliant agents.

You have access to tools that let you:
1. Discover available agents via the A2A Gateway (use discover_agents)
2. Get details about any A2A agent's capabilities (use get_agent_capabilities)
3. Call any A2A agent to perform tasks (use call_agent_via_gateway or call_a2a_agent)

When a user asks you to do something:
1. First, use discover_agents to find what agents are available
2. If needed, use get_agent_capabilities to understand an agent's skills
3. Call the appropriate agent with the right message
4. Return the result to the user

Always discover agents first rather than assuming what's available. Be helpful and concise.
"""


class A2AOrchestratorAgent(mlflow.pyfunc.PythonModel):
    """
    MLflow PyFunc model that orchestrates A2A agents using the official A2A SDK.

    This model can be deployed to Databricks Mosaic AI Framework using agents.deploy()
    and will be discoverable/callable via the Model Serving endpoint.
    """

    def _get_auth_headers(self):
        """Get authentication headers using OBO (On-Behalf-Of) user credentials.

        This uses ModelServingUserCredentials to authenticate as the user making the request,
        enabling fine-grained access control via Unity Catalog.
        """
        import os
        try:
            from databricks.sdk import WorkspaceClient
            from databricks_ai_bridge.utils.credentials import ModelServingUserCredentials

            # Use OBO credentials - authenticates as the user making the request
            w = WorkspaceClient(credentials_strategy=ModelServingUserCredentials())
            return dict(w.config.authenticate())
        except ImportError:
            # Fallback for local development (databricks_ai_bridge not installed)
            try:
                from databricks.sdk import WorkspaceClient
                w = WorkspaceClient()
                return dict(w.config.authenticate())
            except Exception:
                pass
        except Exception as e:
            # Fallback to manual token if OBO fails
            pass

        # Final fallback to environment variable
        auth_token = self._model_config.get("auth_token", "") or os.environ.get("GATEWAY_AUTH_TOKEN", "")
        if auth_token:
            return {"Authorization": f"Bearer {auth_token}"}
        return {}

    def load_context(self, context):
        """Initialize the agent when the model is loaded."""
        from databricks_langchain import ChatDatabricks
        from langchain_core.tools import tool
        from langgraph.prebuilt import create_react_agent
        import httpx
        import os

        # Get configuration
        model_config = context.model_config if hasattr(context, 'model_config') else {}
        endpoint = model_config.get("foundation_model_endpoint", "databricks-meta-llama-3-1-8b-instruct")
        temperature = model_config.get("temperature", 0.1)
        max_tokens = model_config.get("max_tokens", 1000)
        self.gateway_url = model_config.get("gateway_url", "") or os.environ.get("GATEWAY_URL", "")

        # Initialize LLM
        self.llm = ChatDatabricks(
            endpoint=endpoint,
            temperature=temperature,
            max_tokens=max_tokens
        )

        # Store config for tools
        self._model_config = model_config

        # Reference to self for nested functions
        _self = self

        # Define A2A tools
        @tool
        def discover_agents() -> str:
            """Discover available A2A agents via the gateway.

            Returns a list of available agents with their names and descriptions.
            Use this when you need to know what agents are available.
            """
            gateway_url = _self.gateway_url

            if not gateway_url:
                return "Error: Gateway URL not configured"

            headers = _self._get_auth_headers()

            try:
                with httpx.Client(timeout=30.0, headers=headers) as client:
                    response = client.get(f"{gateway_url}/api/agents")
                    response.raise_for_status()
                    data = response.json()

                    agents = data.get("agents", [])
                    if not agents:
                        return "No agents found"

                    result = f"Found {len(agents)} agents:\n"
                    for agent in agents:
                        result += f"- {agent['name']}: {agent.get('description', 'No description')}\n"
                        result += f"  URL: {agent.get('agent_card_url', 'N/A')}\n"

                    return result
            except Exception as e:
                return f"Error discovering agents: {str(e)}"

        @tool
        def get_agent_capabilities(agent_url: str) -> str:
            """Get the capabilities and skills of an A2A agent by fetching its agent card.

            Args:
                agent_url: The base URL of the A2A agent (e.g., https://agent.example.com)

            Returns:
                A description of the agent's name, capabilities, and available skills.
            """
            from a2a.client import A2ACardResolver

            headers = _self._get_auth_headers()
            http_kwargs = {"headers": headers} if headers else {}

            async def _get_card():
                async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
                    resolver = A2ACardResolver(httpx_client=client, base_url=agent_url)
                    return await resolver.get_agent_card(http_kwargs=http_kwargs)

            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    card = loop.run_until_complete(_get_card())
                finally:
                    loop.close()

                result = f"Agent: {card.name}\n"
                result += f"Description: {card.description}\n"
                result += f"Version: {card.version}\n"

                if card.capabilities:
                    result += f"Streaming: {card.capabilities.streaming}\n"

                if card.skills:
                    result += "Skills:\n"
                    for skill in card.skills:
                        result += f"  - {skill.name}: {skill.description}\n"
                        if skill.examples:
                            result += f"    Examples: {', '.join(skill.examples[:3])}\n"

                return result
            except Exception as e:
                return f"Error getting agent capabilities: {str(e)}"

        @tool
        def call_a2a_agent(agent_url: str, message: str) -> str:
            """Call an A2A-compliant agent and get a response.

            Use this tool to send a message to another A2A agent and get its response.
            The agent_url should be the base URL of the agent (not the gateway proxy).

            Args:
                agent_url: The base URL of the A2A agent (e.g., https://agent.example.com)
                message: The message to send to the agent

            Returns:
                The agent's response as a string
            """
            from a2a.client import ClientFactory, ClientConfig
            from a2a.types import Message, Part, TextPart
            from uuid import uuid4

            headers = _self._get_auth_headers()

            async def _call_agent():
                async with httpx.AsyncClient(timeout=60.0, headers=headers) as httpx_client:
                    # Resolve card and fix URL
                    from a2a.client import A2ACardResolver
                    resolver = A2ACardResolver(httpx_client=httpx_client, base_url=agent_url)
                    card = await resolver.get_agent_card(http_kwargs={"headers": headers} if headers else None)
                    if card.url and not card.url.startswith("http"):
                        card.url = agent_url.rstrip("/") + "/" + card.url.lstrip("/")

                    # Create client using ClientFactory
                    config = ClientConfig(httpx_client=httpx_client)
                    factory = ClientFactory(config=config)
                    client = factory.create(card=card)

                    # Create Message object (new SDK API)
                    msg = Message(
                        messageId=str(uuid4()),
                        role="user",
                        parts=[Part(root=TextPart(text=message))]
                    )

                    # Iterate through async iterator - collect final task
                    final_task = None
                    async for event in client.send_message(msg):
                        if isinstance(event, tuple):
                            task, update = event
                            final_task = task

                    # Extract text from task
                    if final_task and final_task.artifacts:
                        for artifact in final_task.artifacts:
                            for part in artifact.parts:
                                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                    return part.root.text

                    return "No response"

            try:
                # Run async function
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(_call_agent())
                finally:
                    loop.close()
            except Exception as e:
                return f"Error calling agent: {str(e)}"

        @tool
        def call_agent_via_gateway(agent_name: str, message: str) -> str:
            """Call an agent through the A2A Gateway using the agent's short name.

            The gateway enforces UC connection access control. Use this when you
            want to call agents by their registered name (e.g., 'marcin-echo').

            Args:
                agent_name: The short name of the agent as registered in the gateway
                message: The message to send to the agent

            Returns:
                The agent's response as a string
            """
            from uuid import uuid4

            gateway_url = _self.gateway_url

            if not gateway_url:
                return "Error: Gateway URL not configured"

            headers = _self._get_auth_headers()
            headers["Content-Type"] = "application/json"

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
                    artifacts = result.get("artifacts", [])

                    for artifact in artifacts:
                        for part in artifact.get("parts", []):
                            if part.get("kind") == "text":
                                return part.get("text", "")

                    return json.dumps(data)
            except Exception as e:
                return f"Error calling agent via gateway: {str(e)}"

        # Create the agent with tools
        self.tools = [discover_agents, get_agent_capabilities, call_a2a_agent, call_agent_via_gateway]
        self.agent = create_react_agent(self.llm, self.tools)
        self.system_prompt = SYSTEM_PROMPT

    def predict(self, context, model_input, params=None) -> dict:
        """Handle prediction requests in Agent Framework format."""
        from langchain_core.messages import SystemMessage
        import pandas as pd

        # Handle pandas DataFrame input (from agents.deploy())
        if isinstance(model_input, pd.DataFrame):
            if "messages" in model_input.columns:
                messages_data = model_input["messages"].iloc[0]
                if isinstance(messages_data, list) and len(messages_data) > 0:
                    query = messages_data[-1].get("content", "")
                else:
                    query = str(messages_data)
            else:
                query = str(model_input.iloc[0, 0])
        # Handle dict input
        elif isinstance(model_input, dict):
            if "messages" in model_input:
                messages_input = model_input["messages"]
                query = messages_input[-1].get("content", "") if messages_input else ""
            elif "input" in model_input:
                query = model_input["input"]
            else:
                query = str(model_input)
        # Handle ChatCompletionRequest object
        elif hasattr(model_input, 'messages'):
            if hasattr(model_input.messages, '__len__') and len(model_input.messages) > 0:
                query = model_input.messages[-1].content
            else:
                query = ""
        else:
            query = str(model_input)

        # Invoke agent
        messages = [
            SystemMessage(content=self.system_prompt),
            {"role": "user", "content": query}
        ]

        response = self.agent.invoke({"messages": messages})

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
