"""
Deploy a simple chat assistant to Azure AI Foundry.

This creates an OpenAI-compatible assistant using the Foundry REST API.
The assistant can be called from UC Functions via the threads/runs API.

Usage:
    python deploy_simple_agent.py          # Create the assistant
    python deploy_simple_agent.py --delete # Delete the assistant
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

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


ASSISTANT_NAME = "simple-chat-agent"
API_VERSION = "2025-05-01"


def get_azure_token():
    """Get Azure AD token for AI Foundry."""
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", "https://ai.azure.com", "--query", "accessToken", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error getting Azure token: {e.stderr}")
        print("Run 'az login' first.")
        sys.exit(1)


def api_call(method, endpoint, path, token, body=None):
    """Make REST API call to Foundry."""
    url = f"{endpoint}{path}?api-version={API_VERSION}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        print(f"HTTP {e.code}: {error_body}")
        return None


def create_agent():
    """Create an OpenAI-compatible assistant via REST API."""
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    if not endpoint:
        print("Error: AZURE_AI_PROJECT_ENDPOINT not set in .env")
        sys.exit(1)

    model = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o")

    print(f"Creating assistant in Azure AI Foundry...")
    print(f"  Endpoint: {endpoint}")
    print(f"  Model: {model}")
    print(f"  Name: {ASSISTANT_NAME}")

    token = get_azure_token()

    result = api_call("POST", endpoint, "/assistants", token, {
        "model": model,
        "name": ASSISTANT_NAME,
        "instructions": """You are a helpful, friendly assistant deployed in Azure AI Foundry.

When responding:
1. Be concise but helpful
2. If asked about your identity, explain you are an Azure AI Foundry agent being called from Databricks

This demonstrates cross-platform agent interoperability - you are a Foundry agent being invoked through a Databricks Unity Catalog function."""
    })

    if not result or "id" not in result:
        print("Error: Failed to create assistant")
        sys.exit(1)

    assistant_id = result["id"]

    # Save assistant ID for reference
    agent_id_file = os.path.join(os.path.dirname(__file__), ".simple_agent_id")
    with open(agent_id_file, "w") as f:
        f.write(assistant_id)

    print(f"\nAssistant created successfully!")
    print(f"  ID: {assistant_id}")
    print(f"  Name: {result.get('name')}")
    print(f"\nTest in Azure AI Foundry portal:")
    print(f"  https://ai.azure.com -> Your project -> Assistants")
    print(f"\nNext steps:")
    print(f"  1. Run: make deploy-uc")
    print(f"  2. Run the notebook to register UC functions")

    return assistant_id


def delete_agent():
    """Delete the assistant via REST API."""
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    if not endpoint:
        print("Error: AZURE_AI_PROJECT_ENDPOINT not set in .env")
        sys.exit(1)

    # Check for saved assistant ID
    agent_id_file = os.path.join(os.path.dirname(__file__), ".simple_agent_id")
    assistant_id = None
    if os.path.exists(agent_id_file):
        with open(agent_id_file) as f:
            assistant_id = f.read().strip()
            # Handle old format "name:version"
            if ":" in assistant_id and not assistant_id.startswith("asst_"):
                print(f"Found old managed agent format: {assistant_id}")
                print("Cleaning up local file.")
                os.remove(agent_id_file)
                return

    if not assistant_id or not assistant_id.startswith("asst_"):
        print(f"No valid assistant ID found")
        return

    token = get_azure_token()

    result = api_call("DELETE", endpoint, f"/assistants/{assistant_id}", token)

    if result is not None:
        print(f"Deleted assistant: {assistant_id}")

    # Clean up local file
    if os.path.exists(agent_id_file):
        os.remove(agent_id_file)


def main():
    parser = argparse.ArgumentParser(description="Manage simple Foundry chat assistant")
    parser.add_argument("--delete", action="store_true", help="Delete the assistant")
    args = parser.parse_args()

    load_env()

    if args.delete:
        delete_agent()
    else:
        create_agent()


if __name__ == "__main__":
    main()
