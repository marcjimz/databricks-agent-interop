"""
Foundry MCP Client

Client for Foundry agents to call Databricks managed MCP servers.
Enables Foundry agents to use UC Functions as MCP tools.
"""
import json
import logging
import os
from typing import Any, Optional
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass
class MCPToolResult:
    """Result from an MCP tool call."""
    success: bool
    content: Any
    error: Optional[str] = None


class FoundryMCPClient:
    """
    MCP Client for calling Databricks managed MCP servers from Foundry.

    This enables Foundry agents to:
    - Discover UC Functions as MCP tools
    - Call UC Functions via MCP protocol
    - Access Databricks resources (Vector Search, Genie, etc.)

    Authentication uses Entra ID, which works seamlessly when
    Foundry and Databricks are in the same tenant.

    Usage:
        client = FoundryMCPClient(
            workspace_url="https://your-workspace.azuredatabricks.net",
            catalog="mcp_agents",
            schema="tools"
        )
        tools = client.list_tools()
        result = client.call_tool("echo", {"message": "Hello!"})
    """

    # Databricks resource ID for token acquisition
    DATABRICKS_RESOURCE_ID = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"

    def __init__(
        self,
        workspace_url: Optional[str] = None,
        catalog: str = "mcp_agents",
        schema: str = "tools",
        token: Optional[str] = None
    ):
        """
        Initialize the MCP client.

        Args:
            workspace_url: Databricks workspace URL (or DATABRICKS_HOST env var)
            catalog: UC catalog containing MCP tool functions
            schema: UC schema containing MCP tool functions
            token: Entra ID token for Databricks (or will acquire automatically)
        """
        self.workspace_url = (
            workspace_url or
            os.getenv("DATABRICKS_HOST") or
            os.getenv("DATABRICKS_WORKSPACE_URL")
        )
        self.catalog = catalog
        self.schema = schema
        self._token = token
        self._tools_cache = None

        if not self.workspace_url:
            raise ValueError(
                "Databricks workspace URL required. Set DATABRICKS_HOST "
                "or pass workspace_url parameter."
            )

        # Normalize URL
        self.workspace_url = self.workspace_url.rstrip("/")
        if not self.workspace_url.startswith("https://"):
            self.workspace_url = f"https://{self.workspace_url}"

    @property
    def mcp_endpoint(self) -> str:
        """Get the MCP endpoint for UC Functions."""
        return f"{self.workspace_url}/api/2.0/mcp/functions/{self.catalog}/{self.schema}"

    @property
    def token(self) -> str:
        """Get authentication token."""
        if self._token:
            return self._token

        # Try Azure Identity (works in Foundry with managed identity)
        try:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            token = credential.get_token(f"{self.DATABRICKS_RESOURCE_ID}/.default")
            return token.token
        except Exception as e:
            logger.debug(f"Azure Identity failed: {e}")

        # Fallback to environment
        token = os.getenv("DATABRICKS_TOKEN")
        if token:
            return token

        raise ValueError(
            "No authentication token available. Ensure Azure Identity is "
            "configured or set DATABRICKS_TOKEN environment variable."
        )

    def _headers(self) -> dict:
        """Build request headers."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def _mcp_request(self, method: str, params: dict = None) -> dict:
        """
        Make an MCP JSON-RPC request.

        Args:
            method: MCP method name
            params: Method parameters

        Returns:
            MCP response result
        """
        request_body = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": method,
            "params": params or {}
        }

        response = requests.post(
            self.mcp_endpoint,
            headers=self._headers(),
            json=request_body,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")

        return data.get("result", {})

    def list_tools(self, use_cache: bool = True) -> list:
        """
        List available MCP tools (UC Functions).

        Args:
            use_cache: Whether to use cached tools list

        Returns:
            List of tool definitions
        """
        if use_cache and self._tools_cache is not None:
            return self._tools_cache

        result = self._mcp_request("tools/list")
        tools = result.get("tools", [])
        self._tools_cache = tools

        logger.info(f"Discovered {len(tools)} MCP tools from {self.catalog}.{self.schema}")
        return tools

    def call_tool(self, name: str, arguments: dict) -> MCPToolResult:
        """
        Call an MCP tool (UC Function).

        Args:
            name: Tool name (function name without catalog.schema prefix)
            arguments: Tool arguments

        Returns:
            MCPToolResult with tool output
        """
        try:
            result = self._mcp_request("tools/call", {
                "name": name,
                "arguments": arguments
            })

            content = result.get("content", [])
            if content:
                # Extract text content
                text_content = next(
                    (c.get("text", "") for c in content if c.get("type") == "text"),
                    ""
                )
                # Try to parse as JSON
                try:
                    parsed = json.loads(text_content)
                    return MCPToolResult(success=True, content=parsed)
                except json.JSONDecodeError:
                    return MCPToolResult(success=True, content=text_content)

            return MCPToolResult(success=True, content=None)

        except Exception as e:
            logger.error(f"MCP tool call failed: {e}")
            return MCPToolResult(success=False, content=None, error=str(e))

    def echo(self, message: str) -> str:
        """
        Call the echo tool for testing.

        Args:
            message: Message to echo

        Returns:
            Echoed message
        """
        result = self.call_tool("echo", {"message": message})
        if result.success:
            return json.dumps(result.content)
        return json.dumps({"error": result.error})

    def call_foundry_agent(
        self,
        agent_name: str,
        message: str,
        thread_id: Optional[str] = None
    ) -> dict:
        """
        Call a Foundry agent through the UC Function wrapper.

        This demonstrates circular interop:
        Foundry → Databricks MCP → UC Function → Foundry Agent

        Args:
            agent_name: Name of the Foundry agent
            message: Message to send
            thread_id: Optional thread ID

        Returns:
            Agent response
        """
        result = self.call_tool("call_foundry_agent", {
            "agent_name": agent_name,
            "message": message,
            "thread_id": thread_id
        })
        return result.content if result.success else {"error": result.error}

    def call_external_api(
        self,
        connection_name: str,
        method: str,
        path: str,
        body: Optional[dict] = None
    ) -> dict:
        """
        Call an external API through UC Connection.

        Args:
            connection_name: UC Connection name
            method: HTTP method
            path: API path
            body: Optional request body

        Returns:
            API response
        """
        result = self.call_tool("call_external_api", {
            "connection_name": connection_name,
            "method": method,
            "path": path,
            "body": json.dumps(body) if body else None
        })
        return result.content if result.success else {"error": result.error}


def create_mcp_tools_for_foundry(
    workspace_url: str,
    catalog: str = "mcp_agents",
    schema: str = "tools"
) -> list:
    """
    Create LangChain-compatible tools from Databricks MCP.

    Use this to give a Foundry agent access to Databricks MCP tools.

    Args:
        workspace_url: Databricks workspace URL
        catalog: UC catalog
        schema: UC schema

    Returns:
        List of LangChain tools
    """
    from langchain_core.tools import tool

    client = FoundryMCPClient(workspace_url, catalog, schema)

    @tool
    def databricks_mcp_echo(message: str) -> str:
        """
        Echo a message through Databricks MCP. Use for testing connectivity.

        Args:
            message: Message to echo
        """
        return client.echo(message)

    @tool
    def databricks_mcp_call_api(
        connection_name: str,
        method: str,
        path: str,
        body: str = None
    ) -> str:
        """
        Call an external API through Databricks UC Connection.

        Use this to access external services with credentials managed by Unity Catalog.

        Args:
            connection_name: Name of the UC HTTP Connection
            method: HTTP method (GET, POST, etc.)
            path: API path
            body: Optional JSON body string
        """
        body_dict = json.loads(body) if body else None
        result = client.call_external_api(connection_name, method, path, body_dict)
        return json.dumps(result)

    return [databricks_mcp_echo, databricks_mcp_call_api]
