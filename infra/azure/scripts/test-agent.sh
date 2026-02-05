#!/bin/bash
#
# Test Azure AI Foundry agent with A2A connection to Databricks Gateway.
#
# This script:
# 1. Gets Terraform outputs for connection info
# 2. Creates a test agent with A2A tool
# 3. Tests calling Databricks agents via the A2A connection
# 4. Cleans up the test agent
#
# Usage:
#   ./test-agent.sh                           # Interactive test
#   ./test-agent.sh "List available agents"   # Run specific query

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="${SCRIPT_DIR}/../terraform"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# -----------------------------------------------------------------------------
# Get Terraform Outputs
# -----------------------------------------------------------------------------

log_info "Getting Terraform outputs..."
cd "$TERRAFORM_DIR"

if [ ! -f "terraform.tfstate" ]; then
    log_error "Terraform state not found. Run 'make deploy-azure' first."
    exit 1
fi

# Export environment variables from Terraform outputs
eval "$(terraform output -json environment_variables | jq -r 'to_entries | .[] | "export \(.key)=\"\(.value)\""')"

log_info "Configuration:"
echo "  Project Endpoint: ${FOUNDRY_PROJECT_ENDPOINT:-not set}"
echo "  Model: ${FOUNDRY_MODEL_DEPLOYMENT_NAME:-not set}"
echo "  A2A Connection: ${A2A_PROJECT_CONNECTION_NAME:-not set}"

if [ -z "$FOUNDRY_PROJECT_ENDPOINT" ]; then
    log_error "FOUNDRY_PROJECT_ENDPOINT not set. Check Terraform deployment."
    exit 1
fi

# -----------------------------------------------------------------------------
# Python Test Script
# -----------------------------------------------------------------------------

USER_QUERY="${1:-}"

log_info "Running A2A agent test..."

python3 << 'PYTHON_SCRIPT'
import os
import sys

try:
    from azure.identity import DefaultAzureCredential
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import PromptAgentDefinition, A2ATool
except ImportError as e:
    print(f"Error: Required packages not installed: {e}")
    print("Install with: pip install azure-ai-projects azure-identity")
    sys.exit(1)

# Get configuration from environment
project_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
model_name = os.environ.get("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4o")
a2a_connection_name = os.environ.get("A2A_PROJECT_CONNECTION_NAME")
a2a_connection_id = os.environ.get("A2A_PROJECT_CONNECTION_ID")

if not all([project_endpoint, a2a_connection_name]):
    print("Error: Missing required environment variables")
    sys.exit(1)

print(f"\n{'='*60}")
print("  Azure AI Foundry A2A Agent Test")
print(f"{'='*60}\n")

try:
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=project_endpoint, credential=credential) as client,
    ):
        print(f"Connected to project: {project_endpoint[:50]}...")

        # Get A2A connection
        print(f"Getting A2A connection: {a2a_connection_name}")
        a2a_connection = client.connections.get(a2a_connection_name)
        print(f"  Connection ID: {a2a_connection.id[:50]}...")

        # Create A2A tool
        tool = A2ATool(project_connection_id=a2a_connection.id)

        # Create test agent
        print(f"\nCreating test agent with A2A tool...")
        agent = client.agents.create_version(
            agent_name="databricks-a2a-test",
            definition=PromptAgentDefinition(
                model=model_name,
                instructions="""You are a helpful assistant that can interact with Databricks agents.

When asked about available agents or to perform tasks, use the A2A tool to:
1. Discover agents by calling the gateway's /api/agents endpoint
2. Send messages to specific agents via /api/agents/{agent_name}

Always explain what you're doing and summarize the responses.""",
                tools=[tool],
            ),
        )
        print(f"  Agent created: {agent.name} (version: {agent.version})")

        # Get user query
        user_query = os.environ.get("USER_QUERY") or sys.argv[1] if len(sys.argv) > 1 else None
        if not user_query:
            user_query = input("\nEnter your query (or press Enter for default): ").strip()
            if not user_query:
                user_query = "What Databricks agents are available? List them."

        print(f"\nQuery: {user_query}")
        print("-" * 60)

        # Get OpenAI client for responses
        openai_client = client.get_openai_client()

        # Send request with streaming
        print("\nResponse:")
        stream_response = openai_client.responses.create(
            stream=True,
            input=user_query,
            extra_body={
                "agent": {"name": agent.name, "type": "agent_reference"},
                "tool_choice": "auto"
            },
        )

        full_response = ""
        for event in stream_response:
            if event.type == "response.output_text.delta":
                print(event.delta, end="", flush=True)
                full_response += event.delta
            elif event.type == "response.output_item.done":
                item = event.item
                if hasattr(item, 'type') and item.type == "remote_function_call":
                    print(f"\n  [A2A Call: {getattr(item, 'label', 'unknown')}]")

        print("\n" + "-" * 60)

        # Cleanup
        print("\nCleaning up test agent...")
        client.agents.delete_version(agent_name=agent.name, agent_version=agent.version)
        print("  Agent deleted.")

        print(f"\n{'='*60}")
        print("  Test completed successfully!")
        print(f"{'='*60}\n")

except Exception as e:
    print(f"\nError: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYTHON_SCRIPT

log_info "Test complete."
