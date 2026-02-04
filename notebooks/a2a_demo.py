# Databricks notebook source
# MAGIC %md
# MAGIC # A2A Protocol Demo Notebook
# MAGIC
# MAGIC This notebook demonstrates the **Agent-to-Agent (A2A) Protocol** via the **A2A Gateway**.
# MAGIC
# MAGIC **All calls go through the gateway** which handles:
# MAGIC - **Authentication** - Passes OAuth token to downstream agents
# MAGIC - **Authorization** - Checks UC connection permissions
# MAGIC - **Tracing** - Logs to MLflow experiment
# MAGIC
# MAGIC **Features demonstrated:**
# MAGIC 1. **Agent Discovery** - Resolve agent cards via gateway
# MAGIC 2. **Message Sending** - JSON-RPC proxy through gateway
# MAGIC 3. **Task Lifecycle** - Get task status via gateway
# MAGIC 4. **Streaming** - Real-time SSE via gateway
# MAGIC 5. **Multi-Agent Orchestration** - Call multiple agents through gateway
# MAGIC
# MAGIC Reference: [A2A Protocol Specification](https://google.github.io/A2A/)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC
# MAGIC ### Configuration
# MAGIC
# MAGIC Default values are loaded from `notebooks/settings.yaml`. URLs are discovered automatically from Databricks Apps.
# MAGIC
# MAGIC ### Getting an OAuth Token
# MAGIC
# MAGIC Databricks Apps require OAuth authentication. Run this command locally to get a token:
# MAGIC
# MAGIC ```bash
# MAGIC databricks auth token --host "${DATABRICKS_HOST}"
# MAGIC ```

# COMMAND ----------

# DBTITLE 1,Install Dependencies
# MAGIC %pip install -r requirements.txt --quiet

# COMMAND ----------

# DBTITLE 1,Restart Python after pip install
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Load Settings and Create Widgets
import yaml
from pathlib import Path

# Load settings from YAML file
possible_paths = [
    Path("/Workspace/Users") / spark.sql("SELECT current_user()").first()[0] / ".bundle/a2a-gateway/dev/files/notebooks/settings.yaml",
    Path("settings.yaml"),
    Path("notebooks/settings.yaml"),
]

settings = {}
for path in possible_paths:
    try:
        with open(path, "r") as f:
            settings = yaml.safe_load(f) or {}
            print(f"Loaded defaults from: {path}")
            break
    except FileNotFoundError:
        continue

if not settings:
    print("No settings.yaml found - using hardcoded defaults")

# Create widgets
dbutils.widgets.text("prefix", settings.get("prefix", "marcin"), "Agent Prefix")
dbutils.widgets.text("access_token", settings.get("access_token", ""), "OAuth Access Token")

# COMMAND ----------

# DBTITLE 1,Configuration
import os
import json
import asyncio
import httpx
from uuid import uuid4

# Enable nested event loops (required for Databricks notebooks)
import nest_asyncio
nest_asyncio.apply()

from databricks.sdk import WorkspaceClient

# Note: A2A SDK not required for gateway calls - using httpx directly
# from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
# from a2a.types import Message, Part, TextPart, TaskQueryParams

# Get configuration from widgets
PREFIX = dbutils.widgets.get("prefix")
ACCESS_TOKEN = dbutils.widgets.get("access_token")

# Validate access token
if not ACCESS_TOKEN:
    raise ValueError(
        "access_token widget is empty!\n\n"
        "To get a token, run this command locally:\n"
        "  databricks auth token --host \"${DATABRICKS_HOST}\"\n\n"
        "Then paste the token into the 'access_token' widget above."
    )

# Discover Gateway URL from Databricks Apps SDK
w = WorkspaceClient()

def get_app_url(app_name: str) -> str:
    """Get the URL for a Databricks App by name."""
    try:
        app = w.apps.get(name=app_name)
        return app.url
    except Exception as e:
        raise ValueError(f"Could not find app '{app_name}': {e}")

# All calls go through the gateway - it handles auth and UC permissions
GATEWAY_URL = get_app_url(f"{PREFIX}-a2a-gateway")

# Agent names for gateway routing (not direct URLs)
ECHO_AGENT_NAME = f"{PREFIX}-echo"
CALC_AGENT_NAME = f"{PREFIX}-calculator"

# Build auth headers
AUTH_HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

print(f"✅ Gateway URL: {GATEWAY_URL}")
print(f"✅ Echo Agent: {ECHO_AGENT_NAME} (via gateway)")
print(f"✅ Calculator Agent: {CALC_AGENT_NAME} (via gateway)")
print(f"✅ Auth Token: Configured ({len(ACCESS_TOKEN)} chars)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. A2A Agent Card Resolution
# MAGIC
# MAGIC The gateway fetches agent cards from downstream agents at `/.well-known/agent.json`.

# COMMAND ----------

# DBTITLE 1,Resolve Agent Cards via Gateway
async def resolve_agent_card_via_gateway(agent_name: str, headers: dict = None):
    """Resolve an agent card through the gateway.

    The gateway fetches the agent card from the downstream agent and
    returns it, handling authentication automatically.
    """
    url = f"{GATEWAY_URL}/api/agents/{agent_name}/.well-known/agent.json"
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

print("═" * 60)
print("ECHO AGENT CARD (via Gateway)")
print("═" * 60)
echo_card = asyncio.run(resolve_agent_card_via_gateway(ECHO_AGENT_NAME, AUTH_HEADERS))
print(f"Name: {echo_card.get('name')}")
print(f"Description: {echo_card.get('description')}")
print(f"Version: {echo_card.get('version')}")
caps = echo_card.get('capabilities', {})
print(f"Capabilities: streaming={caps.get('streaming', 'N/A')}")
print(f"Skills: {[s.get('name') for s in echo_card.get('skills', [])]}")

# COMMAND ----------

# DBTITLE 1,Resolve Calculator Agent Card via Gateway
print("═" * 60)
print("CALCULATOR AGENT CARD (via Gateway)")
print("═" * 60)
calc_card = asyncio.run(resolve_agent_card_via_gateway(CALC_AGENT_NAME, AUTH_HEADERS))
print(f"Name: {calc_card.get('name')}")
print(f"Description: {calc_card.get('description')}")
print(f"Version: {calc_card.get('version')}")
print(f"Skills:")
for skill in calc_card.get('skills', []):
    print(f"  • {skill.get('name')}: {skill.get('description')}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Send Messages via Gateway
# MAGIC
# MAGIC Use JSON-RPC calls through the gateway's `/api/agents/{name}` endpoint.

# COMMAND ----------

# DBTITLE 1,Helper Functions
def extract_text_from_result(result: dict) -> str:
    """Extract text from A2A JSON-RPC result."""
    for artifact in result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("kind") == "text":
                return part.get("text", "")
            elif "text" in part:
                return part.get("text", "")
    return ""


async def call_a2a_agent_via_gateway(agent_name: str, message_text: str, headers: dict = None) -> dict:
    """Call an A2A agent through the gateway using JSON-RPC.

    All agent calls go through the gateway which handles:
    - Authentication (passes token to downstream agents)
    - Authorization (checks UC connection permissions)
    - Tracing (logs to MLflow)

    Args:
        agent_name: The agent name (e.g., "marcin-echo")
        message_text: The message to send
        headers: Auth headers

    Returns:
        Dict with 'text' (response), 'task_id', and 'task_state'
    """
    request_headers = dict(headers) if headers else {}
    request_headers["Content-Type"] = "application/json"

    request_body = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": message_text}]
            }
        }
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{GATEWAY_URL}/api/agents/{agent_name}",
            json=request_body,
            headers=request_headers
        )
        response.raise_for_status()
        data = response.json()

    # Extract result from JSON-RPC response
    result = data.get("result", {})
    task_id = result.get("id")
    status = result.get("status", {})
    state_value = status.get("state") if isinstance(status, dict) else None

    # Extract text from artifacts
    text = ""
    for artifact in result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("kind") == "text":
                text = part.get("text", "")
                break
            elif "text" in part:
                text = part.get("text", "")
                break

    return {
        "text": text,
        "task_id": task_id,
        "task_state": state_value,
        "result": result
    }

# COMMAND ----------

# DBTITLE 1,Test Echo Agent via Gateway
print("Sending message to Echo Agent (via Gateway)...")
print("-" * 40)

response = asyncio.run(call_a2a_agent_via_gateway(
    ECHO_AGENT_NAME,
    "Hello from the A2A Gateway!",
    AUTH_HEADERS
))

print(f"Response: {response['text']}")
print(f"Task ID: {response['task_id']}")
print(f"Task State: {response['task_state']}")

# COMMAND ----------

# DBTITLE 1,Test Calculator Agent via Gateway
operations = [
    "Add 15 and 27",
    "Multiply 6 by 7",
    "Divide 100 by 4",
]

for op in operations:
    print(f"Request: {op}")
    response = asyncio.run(call_a2a_agent_via_gateway(CALC_AGENT_NAME, op, AUTH_HEADERS))
    print(f"Result: {response['text']}")
    print(f"Task State: {response['task_state']}")
    print()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Task Lifecycle Management
# MAGIC
# MAGIC A2A supports async task management with `tasks/get` and `tasks/cancel`.

# COMMAND ----------

# DBTITLE 1,Task Lifecycle Demo via Gateway
async def demo_task_lifecycle():
    """Demonstrate A2A task lifecycle via gateway: send, get status."""
    print("═" * 60)
    print("A2A TASK LIFECYCLE DEMO (via Gateway)")
    print("═" * 60)

    headers = dict(AUTH_HEADERS)
    headers["Content-Type"] = "application/json"

    # Step 1: Send a message
    print("\n1. Sending message...")
    request_body = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": "Multiply 123 by 456"}]
            }
        }
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{GATEWAY_URL}/api/agents/{CALC_AGENT_NAME}",
            json=request_body,
            headers=headers
        )
        response.raise_for_status()
        data = response.json()

    result = data.get("result", {})
    task_id = result.get("id")
    status = result.get("status", {})
    state_value = status.get("state") if isinstance(status, dict) else None

    print(f"   Task ID: {task_id}")
    print(f"   State: {state_value or 'unknown'}")

    # Step 2: Get task status (demonstrates tasks/get via gateway)
    if task_id:
        print("\n2. Getting task status...")
        try:
            status_request = {
                "jsonrpc": "2.0",
                "id": str(uuid4()),
                "method": "tasks/get",
                "params": {"id": task_id}
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{GATEWAY_URL}/api/agents/{CALC_AGENT_NAME}",
                    json=status_request,
                    headers=headers
                )
                if response.status_code == 200:
                    status_data = response.json()
                    status_result = status_data.get("result", {})
                    print(f"   Task ID: {status_result.get('id', task_id)}")
                    print(f"   State: {status_result.get('status', {}).get('state', 'unknown')}")
                else:
                    print(f"   Status check returned: {response.status_code}")
        except Exception as e:
            print(f"   Status check: {e}")

    # Step 3: Show final result
    print("\n3. Final result:")
    text = ""
    for artifact in result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("kind") == "text":
                text = part.get("text", "")
            elif "text" in part:
                text = part.get("text", "")
    print(f"   {text}")

    print("\n" + "═" * 60)

asyncio.run(demo_task_lifecycle())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Streaming with A2A Client
# MAGIC
# MAGIC Stream responses in real-time using SSE.

# COMMAND ----------

# DBTITLE 1,Streaming Demo via Gateway
async def stream_a2a_message_via_gateway(agent_name: str, text: str, headers: dict = None):
    """Stream a message response from an A2A agent via the gateway.

    Uses the gateway's /stream endpoint for SSE streaming.
    """
    request_headers = dict(headers) if headers else {}
    request_headers["Content-Type"] = "application/json"

    request_body = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": text}]
            }
        }
    }

    print("Streaming response (via Gateway):")
    print("-" * 40)

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"{GATEWAY_URL}/api/agents/{agent_name}/stream",
            json=request_body,
            headers=request_headers
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        try:
                            event = json.loads(data)
                            if "result" in event:
                                result = event["result"]
                                state = result.get("status", {}).get("state")
                                if state:
                                    print(f"Task state: {state}")
                                for artifact in result.get("artifacts", []):
                                    for part in artifact.get("parts", []):
                                        if part.get("kind") == "text" or "text" in part:
                                            print(f"Result: {part.get('text', '')}")
                        except json.JSONDecodeError:
                            pass

    print("-" * 40)

print("Testing streaming with Calculator Agent (via Gateway):\n")
asyncio.run(stream_a2a_message_via_gateway(CALC_AGENT_NAME, "What is 999 plus 1?", AUTH_HEADERS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. JSON-RPC Helper Functions
# MAGIC
# MAGIC Alternative helper using the low-level JSON-RPC proxy endpoint.

# COMMAND ----------

# DBTITLE 1,Gateway Proxy Helper
async def call_agent_via_gateway(agent_name: str, text: str, method: str = "message/send") -> dict:
    """Call an agent through the A2A Gateway.

    This uses the gateway's JSON-RPC proxy endpoint which supports:
    - message/send: Send a message
    - tasks/get: Get task status
    - tasks/cancel: Cancel a task

    Args:
        agent_name: The agent name (without -a2a suffix)
        text: The message text (for message/send) or task_id (for tasks/get)
        method: The JSON-RPC method

    Returns:
        The JSON-RPC response
    """
    headers = dict(AUTH_HEADERS)
    headers["Content-Type"] = "application/json"

    # Build JSON-RPC request based on method
    if method == "message/send":
        params = {
            "message": {
                "messageId": str(uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": text}]
            }
        }
    elif method == "tasks/get":
        params = {"id": text}  # text is task_id for this method
    elif method == "tasks/cancel":
        params = {"id": text}
    else:
        params = {}

    request_body = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": method,
        "params": params
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{GATEWAY_URL}/api/agents/{agent_name}",
            json=request_body,
            headers=headers
        )
        response.raise_for_status()
        return response.json()

# COMMAND ----------

# DBTITLE 1,Call Echo Agent via Gateway (JSON-RPC)
print("Calling Echo Agent via Gateway (JSON-RPC)...")
response = asyncio.run(call_agent_via_gateway(ECHO_AGENT_NAME, "Hello via Gateway!"))
print(json.dumps(response, indent=2))

# COMMAND ----------

# DBTITLE 1,Call Calculator Agent via Gateway (JSON-RPC)
print("Calling Calculator Agent via Gateway (JSON-RPC)...")
response = asyncio.run(call_agent_via_gateway(CALC_AGENT_NAME, "Multiply 7 by 8"))
print(json.dumps(response, indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Multi-Agent Workflow
# MAGIC
# MAGIC Orchestrate multiple agents using the A2A Client.

# COMMAND ----------

# DBTITLE 1,Multi-Agent Orchestration via Gateway
async def multi_agent_workflow():
    """Demonstrate a workflow using multiple A2A agents via the gateway."""
    print("═" * 60)
    print("MULTI-AGENT WORKFLOW (via Gateway)")
    print("═" * 60)
    print()

    # Step 1: Test connectivity
    print("Step 1: Testing Echo Agent...")
    echo_result = await call_a2a_agent_via_gateway(ECHO_AGENT_NAME, "System check", AUTH_HEADERS)
    print(f"  ✓ Echo: {echo_result['text']}")
    print()

    # Step 2: Perform calculations
    print("Step 2: Calculations...")
    calculations = [
        ("Revenue", "Multiply 1250 by 12"),
        ("Tax (25%)", "Multiply 15000 by 0.25"),
        ("Net", "Subtract 3750 from 15000")
    ]

    for label, expr in calculations:
        result = await call_a2a_agent_via_gateway(CALC_AGENT_NAME, expr, AUTH_HEADERS)
        print(f"  {label}: {result['text']}")
    print()

    # Step 3: Summary
    print("Step 3: Complete!")
    print("  ✓ Verified connectivity with Echo Agent")
    print("  ✓ Performed 3 calculations")
    print()
    print("═" * 60)

asyncio.run(multi_agent_workflow())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. A2A Client as LangChain Tool
# MAGIC
# MAGIC Wrap the A2A client as a tool for LLM-powered orchestration.

# COMMAND ----------

# DBTITLE 1,A2A Tool Pattern (via Gateway)
from langchain_core.tools import tool

@tool
async def a2a_call(agent_name: str, message: str) -> str:
    """Call any A2A-compliant agent through the gateway.

    Args:
        agent_name: The agent name (e.g., "marcin-calculator")
        message: The message to send

    Returns:
        The agent's response
    """
    result = await call_a2a_agent_via_gateway(agent_name, message, AUTH_HEADERS)
    return result.get("text", "No response")

# Test the tool
print("Testing A2A tool pattern (via Gateway):")
result = asyncio.run(a2a_call.ainvoke({
    "agent_name": CALC_AGENT_NAME,
    "message": "Add 100 and 200"
}))
print(f"Result: {result}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC **All calls go through the A2A Gateway** for authentication, authorization, and tracing.
# MAGIC
# MAGIC | Feature | Endpoint | Description |
# MAGIC |---------|----------|-------------|
# MAGIC | List Agents | `GET /api/agents` | Discover available agents |
# MAGIC | Agent Card | `GET /api/agents/{name}/.well-known/agent.json` | Get agent metadata |
# MAGIC | Send Message | `POST /api/agents/{name}` | JSON-RPC proxy |
# MAGIC | Streaming | `POST /api/agents/{name}/stream` | SSE streaming |
# MAGIC
# MAGIC ### Key Patterns
# MAGIC
# MAGIC 1. **Gateway-First** - All calls go through the gateway for UC access control
# MAGIC 2. **JSON-RPC** - Use `call_a2a_agent_via_gateway()` for message/send
# MAGIC 3. **Task Lifecycle** - Tasks have states: submitted → working → completed
# MAGIC 4. **Tool Pattern** - Wrap gateway client as LangChain tool for LLM orchestration
# MAGIC 5. **Streaming** - Use `/stream` endpoint for real-time SSE responses

# COMMAND ----------

print("Demo complete!")
