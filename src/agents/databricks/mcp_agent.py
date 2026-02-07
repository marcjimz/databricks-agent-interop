"""
Databricks MCP Agent

A Databricks agent that uses UC Functions as MCP tools, enabling
interoperability with external agents (Foundry, etc.) through Unity Catalog.

This agent demonstrates:
1. Calling Foundry agents through UC Functions
2. Accessing external APIs via UC Connections
3. Using Databricks managed MCP infrastructure
"""
import json
import logging
from typing import Any, Optional

import mlflow
from langchain_core.tools import tool
from pyspark.sql import SparkSession

logger = logging.getLogger(__name__)


class DatabricksMCPAgent:
    """
    Databricks agent that uses UC Functions exposed as MCP tools.

    This agent can:
    - Call Foundry agents via UC Function wrappers
    - Access external APIs via UC Connections
    - Use any UC Function as a tool

    The UC Functions are automatically exposed via Databricks managed MCP,
    so external MCP clients can also call the same functions.
    """

    def __init__(
        self,
        catalog: str = "mcp_agents",
        schema: str = "tools",
        llm_endpoint: str = "databricks-meta-llama-3-3-70b-instruct"
    ):
        """
        Initialize the MCP Agent.

        Args:
            catalog: UC catalog containing MCP tool functions
            schema: UC schema containing MCP tool functions
            llm_endpoint: Databricks model serving endpoint for LLM
        """
        self.catalog = catalog
        self.schema = schema
        self.llm_endpoint = llm_endpoint
        self._spark: Optional[SparkSession] = None
        self._agent = None

    @property
    def spark(self) -> SparkSession:
        """Get or create SparkSession."""
        if self._spark is None:
            self._spark = SparkSession.builder.getOrCreate()
        return self._spark

    def _call_uc_function(self, function_name: str, **kwargs) -> str:
        """
        Call a UC Function.

        Args:
            function_name: Name of the function in catalog.schema
            **kwargs: Function arguments

        Returns:
            Function result as string
        """
        full_name = f"{self.catalog}.{self.schema}.{function_name}"

        # Build parameter list
        params = []
        for key, value in kwargs.items():
            if value is None:
                params.append("NULL")
            elif isinstance(value, str):
                # Escape single quotes
                escaped = value.replace("'", "''")
                params.append(f"'{escaped}'")
            elif isinstance(value, (dict, list)):
                escaped = json.dumps(value).replace("'", "''")
                params.append(f"'{escaped}'")
            else:
                params.append(str(value))

        params_str = ", ".join(params)
        query = f"SELECT {full_name}({params_str})"

        logger.debug(f"Executing UC function: {query}")

        try:
            result = self.spark.sql(query).collect()[0][0]
            return result
        except Exception as e:
            logger.error(f"UC function call failed: {e}")
            return json.dumps({"error": str(e)})

    def call_foundry_agent(
        self,
        agent_name: str,
        message: str,
        thread_id: Optional[str] = None
    ) -> dict:
        """
        Call an Azure AI Foundry agent.

        Args:
            agent_name: Name of the Foundry agent
            message: Message to send
            thread_id: Optional thread ID for conversation continuity

        Returns:
            Agent response as dict
        """
        result = self._call_uc_function(
            "call_foundry_agent",
            agent_name=agent_name,
            message=message,
            thread_id=thread_id
        )
        return json.loads(result)

    def call_external_api(
        self,
        connection_name: str,
        method: str,
        path: str,
        body: Optional[dict] = None
    ) -> dict:
        """
        Call an external API using UC Connection credentials.

        Args:
            connection_name: Name of the UC HTTP Connection
            method: HTTP method (GET, POST, etc.)
            path: API path
            body: Optional request body

        Returns:
            API response as dict
        """
        result = self._call_uc_function(
            "call_external_api",
            connection_name=connection_name,
            method=method,
            path=path,
            body=json.dumps(body) if body else None
        )
        return json.loads(result)

    def get_tools(self) -> list:
        """
        Get LangChain tools that wrap UC Functions.

        Returns:
            List of LangChain tools
        """
        agent = self  # Capture for closures

        @tool
        def call_foundry_agent(agent_name: str, message: str, thread_id: str = None) -> str:
            """
            Call an Azure AI Foundry agent.

            Use this when you need to:
            - Get information from a Foundry agent
            - Delegate a task to a specialized Foundry agent
            - Continue a conversation with a Foundry agent

            Args:
                agent_name: The name of the Foundry agent to call
                message: The message to send to the agent
                thread_id: Optional thread ID for continuing a conversation
            """
            result = agent.call_foundry_agent(agent_name, message, thread_id)
            return json.dumps(result)

        @tool
        def call_external_api(
            connection_name: str,
            method: str,
            path: str,
            body: str = None
        ) -> str:
            """
            Call an external API using credentials from a UC Connection.

            Use this when you need to:
            - Fetch data from an external service
            - Create/update resources in external systems
            - Integrate with enterprise APIs

            Args:
                connection_name: Name of the UC HTTP Connection
                method: HTTP method (GET, POST, PUT, DELETE)
                path: API path to call
                body: Optional request body as JSON string
            """
            body_dict = json.loads(body) if body else None
            result = agent.call_external_api(connection_name, method, path, body_dict)
            return json.dumps(result)

        return [call_foundry_agent, call_external_api]

    def create_react_agent(self):
        """
        Create a ReAct agent with MCP tools.

        Returns:
            LangGraph ReAct agent
        """
        from langchain_community.chat_models import ChatDatabricks
        from langgraph.prebuilt import create_react_agent

        llm = ChatDatabricks(
            endpoint=self.llm_endpoint,
            temperature=0.1
        )

        tools = self.get_tools()

        agent = create_react_agent(
            llm,
            tools=tools,
            state_modifier="""You are an assistant that can:
1. Call Azure AI Foundry agents for specialized tasks
2. Access external APIs through secure UC Connections

When a user asks you to do something that requires a Foundry agent or external API,
use the appropriate tool. Always explain what you're doing."""
        )

        self._agent = agent
        return agent

    def invoke(self, message: str) -> str:
        """
        Invoke the agent with a user message.

        Args:
            message: User message

        Returns:
            Agent response
        """
        if self._agent is None:
            self.create_react_agent()

        response = self._agent.invoke({
            "messages": [{"role": "user", "content": message}]
        })

        return response["messages"][-1].content


class DatabricksMCPAgentModel(mlflow.pyfunc.PythonModel):
    """
    MLflow model wrapper for DatabricksMCPAgent.

    Use this for deploying the agent via Mosaic AI Model Serving.
    """

    def __init__(
        self,
        catalog: str = "mcp_agents",
        schema: str = "tools",
        llm_endpoint: str = "databricks-meta-llama-3-3-70b-instruct"
    ):
        self.catalog = catalog
        self.schema = schema
        self.llm_endpoint = llm_endpoint
        self._agent = None

    def load_context(self, context):
        """Initialize the agent when model is loaded."""
        self._agent = DatabricksMCPAgent(
            catalog=self.catalog,
            schema=self.schema,
            llm_endpoint=self.llm_endpoint
        )
        self._agent.create_react_agent()

    def predict(self, context, model_input) -> dict:
        """
        Process a prediction request.

        Args:
            context: MLflow context
            model_input: Dict with 'messages' key

        Returns:
            Dict with 'response' key
        """
        messages = model_input.get("messages", [])
        if messages:
            last_message = messages[-1]
            content = last_message.get("content", "")
            response = self._agent.invoke(content)
            return {"response": response}
        return {"response": "No message provided"}
