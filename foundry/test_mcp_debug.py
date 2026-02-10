"""
Debug script for Foundry Agent + Databricks MCP integration.

Tests each component separately to identify where the failure occurs:
1. Direct MCP server call (bypass Foundry)
2. Azure AI Project client connection
3. Responses API with agent reference (Foundry 2.0 style)

Usage:
    python test_mcp_debug.py

Requires:
    pip install azure-ai-projects azure-identity openai python-dotenv requests
    az login
"""

import os
import sys
import json
import requests
from datetime import datetime

# Add parent dir for .env
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
        print(f"[OK] Loaded .env from {env_path}")
    else:
        print(f"[WARN] No .env file at {env_path}")


def log(step, msg, level="INFO"):
    """Print timestamped log message."""
    ts = datetime.now().strftime("%H:%M:%S")
    symbol = {"INFO": "[*]", "OK": "[+]", "FAIL": "[-]", "DEBUG": "[D]"}.get(level, "[*]")
    print(f"{ts} {symbol} [{step}] {msg}")


def test_1_direct_mcp_call():
    """Test 1: Call MCP server directly using Databricks token."""
    log("TEST-1", "Direct MCP Server Call (bypass Foundry)")
    log("TEST-1", "-" * 50)

    databricks_host = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
    catalog = os.environ.get("UC_CATALOG", "mcp_agents")
    schema = os.environ.get("UC_SCHEMA", "tools")

    mcp_url = f"{databricks_host}/api/2.0/mcp/functions/{catalog}/{schema}"

    log("TEST-1", f"MCP URL: {mcp_url}")

    # Get Databricks token from Azure CLI
    try:
        from azure.identity import AzureCliCredential
        cred = AzureCliCredential()
        # Databricks resource ID
        token = cred.get_token("2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default")
        databricks_token = token.token
        log("TEST-1", f"Got Databricks token (expires: {token.expires_on})", "OK")
    except Exception as e:
        log("TEST-1", f"Failed to get token: {e}", "FAIL")
        return False

    # Test 1a: List tools
    log("TEST-1", "Calling tools/list...")
    headers = {
        "Authorization": f"Bearer {databricks_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/list",
        "params": {}
    }

    try:
        resp = requests.post(mcp_url, headers=headers, json=payload, timeout=30)
        log("TEST-1", f"Response status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            if "result" in data and "tools" in data["result"]:
                tools = data["result"]["tools"]
                log("TEST-1", f"Found {len(tools)} tools:", "OK")
                for t in tools:
                    log("TEST-1", f"  - {t.get('name')}: {t.get('description', '')[:50]}...")
            else:
                log("TEST-1", f"Unexpected response: {json.dumps(data, indent=2)}", "FAIL")
        else:
            log("TEST-1", f"HTTP Error: {resp.text[:500]}", "FAIL")
            return False
    except Exception as e:
        log("TEST-1", f"Request failed: {e}", "FAIL")
        return False

    # Test 1b: Call calculator tool
    log("TEST-1", "Calling calculator_agent tool...")
    tool_name = f"{catalog}__{schema}__calculator_agent"
    payload = {
        "jsonrpc": "2.0",
        "id": "2",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"expression": "add 5 and 3"}
        }
    }

    try:
        resp = requests.post(mcp_url, headers=headers, json=payload, timeout=60)
        log("TEST-1", f"Response status: {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            log("TEST-1", f"Tool response: {json.dumps(data, indent=2)}", "OK")
        else:
            log("TEST-1", f"HTTP Error: {resp.text[:500]}", "FAIL")
            return False
    except Exception as e:
        log("TEST-1", f"Request failed: {e}", "FAIL")
        return False

    log("TEST-1", "Direct MCP call successful!", "OK")
    return True


def test_2_project_client():
    """Test 2: Verify Azure AI Project client connection."""
    log("TEST-2", "Azure AI Project Client Connection")
    log("TEST-2", "-" * 50)

    try:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
    except ImportError as e:
        log("TEST-2", f"Import error: {e}", "FAIL")
        log("TEST-2", "Run: pip install azure-ai-projects azure-identity")
        return False

    # Try multiple endpoint formats
    endpoints_to_try = []

    # From environment
    if os.environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        endpoints_to_try.append(("env", os.environ["AZURE_AI_PROJECT_ENDPOINT"]))

    # Construct from known values (Foundry 2.0 format)
    # Format: https://<resource>.services.ai.azure.com/api/projects/<project>
    location = os.environ.get("LOCATION", "westus")
    subscription_id = os.environ.get("SUBSCRIPTION_ID")
    resource_group = os.environ.get("RESOURCE_GROUP", "rg-mcpagent01")

    # Try common patterns
    endpoints_to_try.extend([
        ("foundry2", f"https://{location}.api.azureml.ms"),
        ("services", f"https://{location}.services.ai.azure.com"),
    ])

    credential = DefaultAzureCredential()

    for name, endpoint in endpoints_to_try:
        log("TEST-2", f"Trying endpoint ({name}): {endpoint}")
        try:
            client = AIProjectClient(endpoint=endpoint, credential=credential)
            # Try a simple operation
            log("TEST-2", f"Client created successfully", "OK")
            return True, client, endpoint
        except Exception as e:
            log("TEST-2", f"Failed: {e}", "DEBUG")

    # Try connection string format (for hub-based projects)
    prefix = os.environ.get("PREFIX", "mcpagent01")
    project_name = f"proj-{prefix}"
    conn_str = f"{location}.api.azureml.ms;{subscription_id};{resource_group};{project_name}"

    log("TEST-2", f"Trying connection string: {conn_str}")
    try:
        client = AIProjectClient.from_connection_string(
            conn_str=conn_str,
            credential=credential
        )
        log("TEST-2", f"Client created from connection string", "OK")
        return True, client, conn_str
    except Exception as e:
        log("TEST-2", f"Connection string failed: {e}", "FAIL")

    return False, None, None


def test_3_responses_api():
    """Test 3: Use OpenAI Responses API with agent reference (Foundry 2.0 style)."""
    log("TEST-3", "Responses API with Agent Reference")
    log("TEST-3", "-" * 50)

    try:
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import PromptAgentDefinition, MCPTool
        from azure.identity import DefaultAzureCredential
    except ImportError as e:
        log("TEST-3", f"Import error: {e}", "FAIL")
        log("TEST-3", "This test requires Foundry 2.0 SDK features")
        return False

    # Need project endpoint for Foundry 2.0
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    if not endpoint:
        log("TEST-3", "AZURE_AI_PROJECT_ENDPOINT not set", "FAIL")
        log("TEST-3", "Set it to: https://<resource>.services.ai.azure.com/api/projects/<project>")
        return False

    databricks_host = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
    catalog = os.environ.get("UC_CATALOG", "mcp_agents")
    schema = os.environ.get("UC_SCHEMA", "tools")
    mcp_url = f"{databricks_host}/api/2.0/mcp/functions/{catalog}/{schema}"
    connection_name = os.environ.get("MCP_PROJECT_CONNECTION_NAME", "databricks_mcp")
    model = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o")

    log("TEST-3", f"Endpoint: {endpoint}")
    log("TEST-3", f"MCP URL: {mcp_url}")
    log("TEST-3", f"Connection: {connection_name}")
    log("TEST-3", f"Model: {model}")

    credential = DefaultAzureCredential()

    try:
        with AIProjectClient(endpoint=endpoint, credential=credential) as project_client:
            # List available connections to verify databricks_mcp exists
            log("TEST-3", "Listing project connections...")
            try:
                connections = list(project_client.connections.list())
                log("TEST-3", f"Found {len(connections)} connections:", "OK")
                for conn in connections:
                    conn_type = getattr(conn, 'connection_type', 'unknown')
                    log("TEST-3", f"  - {conn.name} (type: {conn_type})")
                    if conn.name == connection_name:
                        log("TEST-3", f"    ^ This is our MCP connection!", "OK")
            except Exception as e:
                log("TEST-3", f"Could not list connections: {e}", "DEBUG")

            openai_client = project_client.get_openai_client()
            log("TEST-3", "Got OpenAI client from project", "OK")

            # Try to list models/deployments
            log("TEST-3", "Checking available models...")
            try:
                models = openai_client.models.list()
                log("TEST-3", f"Available models:", "OK")
                for m in models:
                    log("TEST-3", f"  - {m.id}")
            except Exception as e:
                log("TEST-3", f"Could not list models: {e}", "DEBUG")

            # Check connection details for the databricks connection
            log("TEST-3", "Checking connection properties...")
            try:
                for conn in connections:
                    log("TEST-3", f"Connection '{conn.name}' properties:")
                    for attr in dir(conn):
                        if not attr.startswith('_'):
                            try:
                                val = getattr(conn, attr)
                                if not callable(val):
                                    log("TEST-3", f"    {attr}: {val}")
                            except:
                                pass
            except Exception as e:
                log("TEST-3", f"Could not inspect connections: {e}", "DEBUG")

            # Define MCP tool
            mcp_tool = MCPTool(
                server_label="databricks_mcp",
                server_url=mcp_url,
                require_approval="never",
                project_connection_id=connection_name,
            )
            log("TEST-3", f"MCP Tool: {mcp_tool}", "DEBUG")

            # Create agent version
            agent = project_client.agents.create_version(
                agent_name="mcp-debug-test",
                definition=PromptAgentDefinition(
                    model=model,
                    instructions="Use the epic_patient_search tool to search for patients. Always use tools.",
                    tools=[mcp_tool],
                ),
            )
            log("TEST-3", f"Agent created: name={agent.name}, version={agent.version}", "OK")

            try:
                # Call via Responses API
                log("TEST-3", "Sending request via Responses API...")
                response = openai_client.responses.create(
                    model=model,
                    input=[{"role": "user", "content": "Search for patients with family name Argonaut"}],
                    extra_body={
                        "agent": {"name": agent.name, "type": "agent_reference"}
                    },
                )

                log("TEST-3", f"Response id: {response.id}", "OK")
                log("TEST-3", f"Response status: {response.status}")

                # Inspect output
                log("TEST-3", "Output items:")
                for i, item in enumerate(response.output):
                    log("TEST-3", f"  [{i}] type={item.type}")
                    if hasattr(item, 'server_label'):
                        log("TEST-3", f"      server_label={item.server_label}")
                    if hasattr(item, 'name'):
                        log("TEST-3", f"      name={item.name}")
                    if hasattr(item, 'arguments'):
                        log("TEST-3", f"      arguments={item.arguments}")
                    if item.type == "mcp_call":
                        log("TEST-3", f"      MCP CALL DETECTED!", "OK")
                    if item.type == "mcp_call_output":
                        log("TEST-3", f"      MCP OUTPUT: {getattr(item, 'output', 'N/A')}", "OK")
                    if item.type == "message":
                        for content in item.content:
                            if hasattr(content, 'text'):
                                log("TEST-3", f"      text: {content.text[:200]}")

                # Check for OAuth consent requests
                oauth_consent_items = [item for item in response.output if item.type == "oauth_consent_request"]
                if oauth_consent_items:
                    log("TEST-3", f"Found {len(oauth_consent_items)} OAuth consent request(s)", "OK")
                    log("TEST-3", "=" * 50)
                    log("TEST-3", "OAuth Consent Required", "OK")
                    log("TEST-3", "=" * 50)

                    for item in oauth_consent_items:
                        consent_link = getattr(item, 'consent_link', None)
                        log("TEST-3", f"Server Label: {item.server_label}")
                        log("TEST-3", f"Request ID: {item.id}")
                        if consent_link:
                            log("TEST-3", "")
                            log("TEST-3", "Please open this URL in your browser to authorize:")
                            log("TEST-3", f"  {consent_link}")
                            log("TEST-3", "")

                    # Wait for user to complete consent
                    input("Press Enter after completing OAuth consent in your browser...")

                    # Retry the request after consent
                    log("TEST-3", "Retrying request after OAuth consent...")
                    response = openai_client.responses.create(
                        model=model,
                        input=[{"role": "user", "content": "Search for patients with family name Argonaut"}],
                        extra_body={
                            "agent": {"name": agent.name, "type": "agent_reference"},
                            "previous_response_id": response.id,
                        },
                    )

                    log("TEST-3", f"Retry Response id: {response.id}", "OK")
                    log("TEST-3", f"Retry Response status: {response.status}")

                    # Check output again
                    for i, item in enumerate(response.output):
                        log("TEST-3", f"  [{i}] type={item.type}")
                        if item.type == "mcp_call":
                            log("TEST-3", f"      MCP CALL DETECTED!", "OK")
                        if item.type == "mcp_call_output":
                            log("TEST-3", f"      MCP OUTPUT: {getattr(item, 'output', 'N/A')}", "OK")
                        if item.type == "message":
                            for content in item.content:
                                if hasattr(content, 'text'):
                                    log("TEST-3", f"      text: {content.text[:500]}")

                # Check for MCP approval requests
                approval_items = [item for item in response.output if item.type == "mcp_approval_request"]
                if approval_items:
                    log("TEST-3", f"Found {len(approval_items)} MCP approval requests - tool invocation attempted!", "OK")
                    log("TEST-3", "This means the agent IS trying to call the MCP tool")
                    log("TEST-3", "But require_approval might not be 'never'")

                # Final answer
                if hasattr(response, 'output_text'):
                    log("TEST-3", f"Final answer: {response.output_text}", "OK")

                return True

            finally:
                # Cleanup
                try:
                    project_client.agents.delete_version(agent.name, agent.version)
                    log("TEST-3", "Agent deleted", "OK")
                except Exception as cleanup_err:
                    log("TEST-3", f"Cleanup failed: {cleanup_err}", "DEBUG")

    except Exception as e:
        log("TEST-3", f"Error: {e}", "FAIL")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("Foundry + Databricks MCP Debug Script")
    print("=" * 60)
    print()

    load_env()
    print()

    # Show configuration
    print("Configuration:")
    print(f"  DATABRICKS_HOST: {os.environ.get('DATABRICKS_HOST', 'NOT SET')}")
    print(f"  UC_CATALOG: {os.environ.get('UC_CATALOG', 'NOT SET')}")
    print(f"  UC_SCHEMA: {os.environ.get('UC_SCHEMA', 'NOT SET')}")
    print(f"  AZURE_AI_PROJECT_ENDPOINT: {os.environ.get('AZURE_AI_PROJECT_ENDPOINT', 'NOT SET')}")
    print(f"  MCP_PROJECT_CONNECTION_NAME: {os.environ.get('MCP_PROJECT_CONNECTION_NAME', 'NOT SET')}")
    print(f"  MODEL_DEPLOYMENT_NAME: {os.environ.get('MODEL_DEPLOYMENT_NAME', 'gpt-4o')}")
    print()

    results = {}

    # Run tests
    print("\n" + "=" * 60)
    results["TEST-1"] = test_1_direct_mcp_call()

    print("\n" + "=" * 60)
    success, _, _ = test_2_project_client()
    results["TEST-2"] = success

    print("\n" + "=" * 60)
    results["TEST-3"] = test_3_responses_api()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test}: {status}")

    print()
    if all(results.values()):
        print("All tests passed!")
    else:
        print("Some tests failed. Check the output above for details.")
        if not results.get("TEST-1"):
            print("\nTEST-1 failed: Direct MCP call failed")
            print("  -> Check Databricks token/permissions")
            print("  -> Verify UC functions are registered")
        if not results.get("TEST-2"):
            print("\nTEST-2 failed: Project client connection failed")
            print("  -> Check AZURE_AI_PROJECT_ENDPOINT")
            print("  -> Verify az login credentials")
        if not results.get("TEST-3"):
            print("\nTEST-3 failed: Responses API failed")
            print("  -> This requires Foundry 2.0 project")
            print("  -> Check project_connection_id matches Foundry connection name")


if __name__ == "__main__":
    main()
