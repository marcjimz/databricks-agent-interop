"""
UC Function: Foundry Agent Wrapper

Defines the UC Python Function that wraps Azure AI Foundry agents,
enabling them to be called via Databricks managed MCP servers.

Usage:
    1. Use FunctionRegistry.register_all() to generate registration SQL
    2. Execute the SQL in Databricks to create the UC Function
    3. Function is automatically exposed at:
       https://<workspace>/api/2.0/mcp/functions/{catalog}/{schema}/call_foundry_agent
"""

# The Python code that runs inside the UC Function
FOUNDRY_FUNCTION_CODE = '''
import json
import requests
import os
import time

def call_foundry_agent(
    agent_name: str,
    message: str,
    thread_id: str = None
) -> str:
    """
    Call an Azure AI Foundry agent.

    Uses Entra ID OBO token for seamless same-tenant authentication.
    The caller's identity is preserved end-to-end.

    Args:
        agent_name: Name of the Foundry agent
        message: User message to send
        thread_id: Optional thread ID for conversation continuity

    Returns:
        JSON string with agent response
    """
    # Get Foundry endpoint from environment
    foundry_endpoint = os.getenv("AZURE_AI_FOUNDRY_ENDPOINT")

    if not foundry_endpoint:
        return json.dumps({"error": "AZURE_AI_FOUNDRY_ENDPOINT not configured"})

    # Get the caller's OBO token from Databricks context
    try:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        token = spark.conf.get("spark.databricks.passthrough.oauthToken", None)
    except Exception:
        token = os.getenv("AZURE_TOKEN")

    if not token:
        return json.dumps({
            "error": "No authentication token. Ensure credential passthrough is enabled."
        })

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "api-version": "2024-12-01-preview"
    }

    try:
        # Create thread if needed
        if not thread_id:
            thread_resp = requests.post(
                f"{foundry_endpoint}/agents/{agent_name}/threads",
                headers=headers,
                json={},
                timeout=10
            )
            if thread_resp.status_code != 200:
                return json.dumps({
                    "error": f"Failed to create thread: {thread_resp.text}"
                })
            thread_id = thread_resp.json().get("id")

        # Add message
        requests.post(
            f"{foundry_endpoint}/agents/{agent_name}/threads/{thread_id}/messages",
            headers=headers,
            json={"role": "user", "content": message},
            timeout=10
        )

        # Run agent
        run_resp = requests.post(
            f"{foundry_endpoint}/agents/{agent_name}/threads/{thread_id}/runs",
            headers=headers,
            json={"assistant_id": agent_name},
            timeout=10
        )
        if run_resp.status_code != 200:
            return json.dumps({"error": f"Failed to run agent: {run_resp.text}"})

        run_id = run_resp.json().get("id")

        # Poll for completion (max 60 seconds)
        for _ in range(60):
            status_resp = requests.get(
                f"{foundry_endpoint}/agents/{agent_name}/threads/{thread_id}/runs/{run_id}",
                headers=headers,
                timeout=10
            )
            status = status_resp.json().get("status")

            if status == "completed":
                # Get response
                msgs_resp = requests.get(
                    f"{foundry_endpoint}/agents/{agent_name}/threads/{thread_id}/messages",
                    headers=headers,
                    params={"order": "desc", "limit": 1},
                    timeout=10
                )
                messages = msgs_resp.json().get("data", [])
                if messages:
                    content = messages[0].get("content", [])
                    text = next(
                        (c.get("text", {}).get("value", "")
                         for c in content if c.get("type") == "text"),
                        ""
                    )
                    return json.dumps({
                        "status": "success",
                        "agent_name": agent_name,
                        "thread_id": thread_id,
                        "response": text
                    })

            elif status in ["failed", "cancelled"]:
                return json.dumps({"error": f"Agent run {status}"})

            time.sleep(1)

        return json.dumps({"error": "Agent run timed out", "thread_id": thread_id})

    except Exception as e:
        return json.dumps({"error": str(e)})
'''


class FoundryAgentFunction:
    """
    UC Function definition for calling Foundry agents.

    This class provides:
    - The function code as a string
    - SQL generation for registration
    - Metadata for discovery
    """

    name = "call_foundry_agent"
    description = "Call an Azure AI Foundry agent with Entra ID OBO authentication"
    code = FOUNDRY_FUNCTION_CODE

    @classmethod
    def get_registration_sql(cls, catalog: str, schema: str) -> str:
        """
        Generate SQL to register this function in Unity Catalog.

        Args:
            catalog: Target catalog name
            schema: Target schema name

        Returns:
            SQL statement to create the function
        """
        return f"""
CREATE OR REPLACE FUNCTION {catalog}.{schema}.{cls.name}(
    agent_name STRING COMMENT 'Name of the Foundry agent to call',
    message STRING COMMENT 'User message to send to the agent',
    thread_id STRING DEFAULT NULL COMMENT 'Thread ID for conversation continuity'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: {cls.description}'
AS $$
{cls.code}

return call_foundry_agent(agent_name, message, thread_id)
$$;
"""

    @classmethod
    def get_mcp_endpoint(cls, workspace_url: str, catalog: str, schema: str) -> str:
        """Get the MCP endpoint for this function."""
        return f"{workspace_url}/api/2.0/mcp/functions/{catalog}/{schema}/{cls.name}"
