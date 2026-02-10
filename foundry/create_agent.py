"""
Create a persistent Azure AI Foundry agent with Databricks MCP tools.

This agent is available in the Foundry portal for testing and tracing.

Usage:
    python create_agent.py          # Create/update the agent
    python create_agent.py --delete # Delete the agent
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env():
    """Load environment variables from .env file."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def create_agent():
    """Create the Foundry agent with Databricks MCP tools."""
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition, MCPTool
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    if not endpoint:
        print("Error: AZURE_AI_PROJECT_ENDPOINT not set in .env")
        sys.exit(1)

    databricks_host = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
    catalog = os.environ.get("UC_CATALOG", "mcp_agents")
    schema = os.environ.get("UC_SCHEMA", "tools")
    mcp_url = f"{databricks_host}/api/2.0/mcp/functions/{catalog}/{schema}"
    connection_name = os.environ.get("MCP_PROJECT_CONNECTION_NAME", "databricks-oauth")
    model = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1")

    print("Creating Foundry agent with Databricks MCP tools...")
    print(f"  Endpoint: {endpoint}")
    print(f"  MCP URL: {mcp_url}")
    print(f"  Connection: {connection_name}")
    print(f"  Model: {model}")

    credential = DefaultAzureCredential()

    with AIProjectClient(endpoint=endpoint, credential=credential) as client:
        mcp_tool = MCPTool(
            server_label="databricks_mcp",
            server_url=mcp_url,
            require_approval="never",
            project_connection_id=connection_name,
        )

        agent = client.agents.create_version(
            agent_name="databricks-mcp-agent",
            definition=PromptAgentDefinition(
                model=model,
                instructions="""You are a helpful assistant with access to Databricks Unity Catalog functions via MCP.

Available tools:
- calculator_agent: Evaluate math expressions (e.g., "add 5 and 3")
- epic_patient_search: Search for patients (family_name, given_name, birthdate)
- foundry_chat_agent: Chat with Azure AI

Use the appropriate tool based on the user's request.""",
                tools=[mcp_tool],
            ),
        )

        print(f"\nAgent created!")
        print(f"  Name: {agent.name}")
        print(f"  Version: {agent.version}")
        print(f"\nTest in Azure AI Foundry portal:")
        print(f"  https://ai.azure.com")
        print(f"  -> Your project -> Agents -> {agent.name}")


def delete_agent():
    """Delete all versions of the agent."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    if not endpoint:
        print("Error: AZURE_AI_PROJECT_ENDPOINT not set in .env")
        sys.exit(1)

    credential = DefaultAzureCredential()

    with AIProjectClient(endpoint=endpoint, credential=credential) as client:
        try:
            # List and delete all versions
            versions = list(client.agents.list_versions("databricks-mcp-agent"))
            for v in versions:
                client.agents.delete_version("databricks-mcp-agent", v.version)
                print(f"Deleted version {v.version}")
            print("Agent deleted")
        except Exception as e:
            print(f"Error deleting agent: {e}")


def main():
    parser = argparse.ArgumentParser(description="Manage Foundry agent with Databricks MCP")
    parser.add_argument("--delete", action="store_true", help="Delete the agent")
    args = parser.parse_args()

    load_env()

    if args.delete:
        delete_agent()
    else:
        create_agent()


if __name__ == "__main__":
    main()
