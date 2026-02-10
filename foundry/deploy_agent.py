"""
Deploy Azure AI Foundry Agent with Databricks MCP Tools

This script creates an Azure AI Foundry agent that can call Databricks UC functions
via MCP (Model Context Protocol), demonstrating cross-platform agent interoperability.

For OAuth authentication, the connection must be configured via Foundry portal
as the SDK doesn't yet fully support project_connection_id in hub-based projects.

Usage:
    python deploy_agent.py --create    # Create and deploy the agent
    python deploy_agent.py --delete    # Delete the agent

Environment Variables (from .env):
    DATABRICKS_HOST         - Databricks workspace URL
    TENANT_ID               - Azure AD tenant ID
    SUBSCRIPTION_ID         - Azure subscription ID
    LOCATION                - Azure region (e.g., westus2)
    PREFIX                  - Resource prefix (e.g., mcp-agent-interop)
    UC_CATALOG              - Unity Catalog catalog name
    UC_SCHEMA               - Unity Catalog schema name
"""

import argparse
import os
import sys

# Add parent directory to path for loading .env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from azure.ai.projects import AIProjectClient
    from azure.ai.agents.models import McpTool
    from azure.identity import DefaultAzureCredential
except ImportError as e:
    print(f"Error: Required packages not installed: {e}")
    print("Run: pip install 'azure-ai-projects>=1.0.0' azure-identity")
    sys.exit(1)


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


def get_config():
    """Get configuration from environment."""
    load_env()

    required = ["DATABRICKS_HOST", "TENANT_ID", "SUBSCRIPTION_ID", "LOCATION"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("Make sure .env file exists with these values.")
        sys.exit(1)

    databricks_host = os.environ["DATABRICKS_HOST"].rstrip("/")
    catalog = os.environ.get("UC_CATALOG", "mcp_agents")
    schema = os.environ.get("UC_SCHEMA", "tools")
    location = os.environ["LOCATION"]
    subscription_id = os.environ["SUBSCRIPTION_ID"]
    prefix = os.environ.get("PREFIX", "mcp-agent-interop")
    resource_group = os.environ.get("RESOURCE_GROUP", f"rg-{prefix}")
    project_name = f"proj-{prefix}"

    # Construct MCP server URL for Databricks managed MCP
    mcp_server_url = f"{databricks_host}/api/2.0/mcp/functions/{catalog}/{schema}"

    # Connection string format for hub-based projects
    # Format: <region>.api.azureml.ms;<subscription_id>;<resource_group>;<workspace_name>
    connection_string = f"{location}.api.azureml.ms;{subscription_id};{resource_group};{project_name}"

    return {
        "connection_string": connection_string,
        "mcp_server_url": mcp_server_url,
        "mcp_server_label": "databricks_mcp",
        "databricks_host": databricks_host,
        "catalog": catalog,
        "schema": schema,
        "tenant_id": os.environ["TENANT_ID"],
        "model_deployment": os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o"),
        "project_name": project_name,
        "resource_group": resource_group,
        "mcp_connection_id": "databricks-mcp-connection",
    }


def create_agent(config):
    """Create the Azure AI Foundry agent with Databricks MCP tools."""
    print("=" * 60)
    print("Creating Azure AI Foundry Agent with Databricks MCP Tools")
    print("=" * 60)

    print(f"\nConfiguration:")
    print(f"  Connection String: {config['connection_string']}")
    print(f"  MCP Server URL:    {config['mcp_server_url']}")
    print(f"  MCP Connection:    {config['mcp_connection_id']}")
    print(f"  Model Deployment:  {config['model_deployment']}")

    # Create MCP tool configuration
    allowed_tools = [
        f"{config['catalog']}__{config['schema']}__calculator_agent",
        f"{config['catalog']}__{config['schema']}__epic_patient_search",
        f"{config['catalog']}__{config['schema']}__foundry_chat_agent",
    ]

    # Create MCP tool - OAuth connection configured via portal
    mcp_tool = McpTool(
        server_label=config["mcp_server_label"],
        server_url=config["mcp_server_url"],
        allowed_tools=allowed_tools,
    )
    mcp_tool.set_approval_mode("never")

    print(f"\nMCP Tool Configuration:")
    print(f"  Server Label:       {mcp_tool.server_label}")
    print(f"  Server URL:         {mcp_tool.server_url}")
    print(f"  Allowed Tools:      {allowed_tools}")

    # Initialize project client using connection string (for hub-based projects)
    credential = DefaultAzureCredential()

    project_client = AIProjectClient.from_connection_string(
        conn_str=config["connection_string"],
        credential=credential,
    )

    with project_client:
        agents_client = project_client.agents

        # Create the agent with MCP tool
        agent = agents_client.create_agent(
            model=config["model_deployment"],
            name="databricks-mcp-agent",
            instructions="""You are a helpful assistant that can use Databricks UC functions via MCP.

Available tools:
1. calculator_agent - Evaluate math expressions (e.g., "add 5 and 3", "multiply 10 by 4")
2. epic_patient_search - Search for patients in Epic FHIR (family_name, given_name, birthdate)
3. foundry_chat_agent - Chat with Azure AI (answers are spelled out)

When a user asks a math question, use the calculator_agent tool.
When a user asks about patients, use the epic_patient_search tool.
For general questions, use the foundry_chat_agent tool.

Always explain what tool you're using and present the results clearly.""",
            tools=mcp_tool.definitions,
            tool_resources=mcp_tool.resources,
        )

        print(f"\n{'=' * 60}")
        print("Agent Created Successfully!")
        print(f"{'=' * 60}")
        print(f"  Agent ID:   {agent.id}")
        print(f"  Agent Name: {agent.name}")
        print(f"  Model:      {agent.model}")

        # Save agent ID for later use
        agent_file = os.path.join(os.path.dirname(__file__), ".agent_id")
        with open(agent_file, "w") as f:
            f.write(agent.id)
        print(f"\n  Agent ID saved to: {agent_file}")

        print(f"\n{'=' * 60}")
        print("OAuth Configuration:")
        print(f"{'=' * 60}")
        print("  The MCP connection uses AgenticIdentityToken for OAuth.")
        print("  This was configured via: make setup-databricks-mcp-connection")
        print("")
        print("  Connection details:")
        print(f"    - Name: {config['mcp_connection_id']}")
        print(f"    - Target: {config['mcp_server_url']}")
        print("    - Auth Type: AgenticIdentityToken")
        print("    - Audience: 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d (Databricks)")

        print(f"\n{'=' * 60}")
        print("Next Steps:")
        print(f"{'=' * 60}")
        print("  1. Go to Azure AI Foundry: https://ai.azure.com")
        print(f"  2. Navigate to project: {config['project_name']}")
        print("  3. Go to Agents > Playgrounds")
        print("  4. Select agent: databricks-mcp-agent")
        print("  5. Test with: 'What is 15 plus 27?'")

        return agent


def delete_agent(config):
    """Delete the Azure AI Foundry agent."""
    agent_file = os.path.join(os.path.dirname(__file__), ".agent_id")

    if not os.path.exists(agent_file):
        print("Error: No agent found. Create an agent first with --create")
        return False

    with open(agent_file) as f:
        agent_id = f.read().strip()

    print(f"Deleting agent: {agent_id}")

    credential = DefaultAzureCredential()

    project_client = AIProjectClient.from_connection_string(
        conn_str=config["connection_string"],
        credential=credential,
    )

    with project_client:
        agents_client = project_client.agents
        agents_client.delete_agent(agent_id)
        print("Agent deleted successfully")

    os.remove(agent_file)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Azure AI Foundry Agent with Databricks MCP Tools"
    )
    parser.add_argument("--create", action="store_true", help="Create the agent")
    parser.add_argument("--delete", action="store_true", help="Delete the agent")

    args = parser.parse_args()

    if not any([args.create, args.delete]):
        parser.print_help()
        return

    config = get_config()

    if args.create:
        create_agent(config)
    elif args.delete:
        delete_agent(config)


if __name__ == "__main__":
    main()
