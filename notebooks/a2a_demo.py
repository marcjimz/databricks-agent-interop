# Databricks notebook source
# MAGIC %md
# MAGIC # A2A Protocol Demo Notebook
# MAGIC
# MAGIC This notebook demonstrates the **Agent-to-Agent (A2A) Protocol** using the official **A2A SDK Client**.
# MAGIC
# MAGIC **Features demonstrated:**
# MAGIC 1. **Agent Discovery** - Resolve agent cards via `A2ACardResolver`
# MAGIC 2. **A2A Client** - Send messages using `A2AClient`
# MAGIC 3. **Task Lifecycle** - Get task status, cancel tasks
# MAGIC 4. **Streaming** - Real-time SSE responses
# MAGIC 5. **Multi-Agent Orchestration** - Call multiple agents
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

# A2A SDK imports
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import Message, Part, TextPart, MessageSendParams

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

# Discover URLs from Databricks Apps SDK
w = WorkspaceClient()

def get_app_url(app_name: str) -> str:
    """Get the URL for a Databricks App by name."""
    try:
        app = w.apps.get(name=app_name)
        return app.url
    except Exception as e:
        raise ValueError(f"Could not find app '{app_name}': {e}")

GATEWAY_URL = get_app_url(f"{PREFIX}-a2a-gateway")
ECHO_AGENT_URL = get_app_url(f"{PREFIX}-echo-agent")
CALC_AGENT_URL = get_app_url(f"{PREFIX}-calculator-agent")

# Build auth headers
AUTH_HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

print(f"✅ Gateway URL: {GATEWAY_URL}")
print(f"✅ Echo Agent URL: {ECHO_AGENT_URL}")
print(f"✅ Calculator Agent URL: {CALC_AGENT_URL}")
print(f"✅ Auth Token: Configured ({len(ACCESS_TOKEN)} chars)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. A2A Agent Card Resolution
# MAGIC
# MAGIC The `A2ACardResolver` fetches and parses the agent card from `/.well-known/agent.json`.

# COMMAND ----------

# DBTITLE 1,Resolve Agent Cards
async def resolve_agent_card(base_url: str, headers: dict = None):
    """Resolve an agent card using A2ACardResolver."""
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        resolver = A2ACardResolver(httpx_client=client, base_url=base_url)
        card = await resolver.get_agent_card(http_kwargs={"headers": headers} if headers else None)
        return card

print("═" * 60)
print("ECHO AGENT CARD")
print("═" * 60)
echo_card = asyncio.run(resolve_agent_card(ECHO_AGENT_URL, AUTH_HEADERS))
print(f"Name: {echo_card.name}")
print(f"Description: {echo_card.description}")
print(f"Version: {echo_card.version}")
print(f"Capabilities: streaming={echo_card.capabilities.streaming if echo_card.capabilities else 'N/A'}")
print(f"Skills: {[s.name for s in echo_card.skills] if echo_card.skills else []}")

# COMMAND ----------

# DBTITLE 1,Resolve Calculator Agent Card
print("═" * 60)
print("CALCULATOR AGENT CARD")
print("═" * 60)
calc_card = asyncio.run(resolve_agent_card(CALC_AGENT_URL, AUTH_HEADERS))
print(f"Name: {calc_card.name}")
print(f"Description: {calc_card.description}")
print(f"Version: {calc_card.version}")
print(f"Skills:")
for skill in calc_card.skills or []:
    print(f"  • {skill.name}: {skill.description}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Send Messages with A2A Client
# MAGIC
# MAGIC Use `A2AClient` for direct communication with A2A agents.

# COMMAND ----------

# DBTITLE 1,A2A Client Helper
def extract_text_from_task(task) -> str:
    """Extract text from A2A Task response."""
    if task and task.artifacts:
        for artifact in task.artifacts:
            for part in artifact.parts:
                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                    return part.root.text
    return ""


async def call_a2a_agent(base_url: str, message_text: str, headers: dict = None) -> dict:
    """Call an A2A agent using the official SDK.

    This is the reference implementation for calling A2A agents directly.

    Args:
        base_url: The base URL of the A2A agent
        message_text: The message to send
        headers: Optional auth headers

    Returns:
        Dict with 'text' (response), 'task_id', and 'task_state'
    """
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as httpx_client:
        # Resolve agent card
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
        card = await resolver.get_agent_card(http_kwargs={"headers": headers} if headers else None)

        # Fix relative URL
        if card.url and not card.url.startswith("http"):
            card.url = base_url.rstrip("/") + "/" + card.url.lstrip("/")

        # Create A2A client
        client = A2AClient(httpx_client=httpx_client, agent_card=card)

        # Create message
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text=message_text))]
        )

        # Send message and collect response
        final_task = None
        async for event in client.send_message(MessageSendParams(message=message)):
            if isinstance(event, tuple):
                task, _ = event
                final_task = task

        return {
            "text": extract_text_from_task(final_task) if final_task else "",
            "task_id": final_task.id if final_task else None,
            "task_state": final_task.status.state.value if final_task and final_task.status else None,
            "task": final_task
        }

# COMMAND ----------

# DBTITLE 1,Test Echo Agent
print("Sending message to Echo Agent...")
print("-" * 40)

response = asyncio.run(call_a2a_agent(
    ECHO_AGENT_URL,
    "Hello from the A2A SDK Client!",
    AUTH_HEADERS
))

print(f"Response: {response['text']}")
print(f"Task ID: {response['task_id']}")
print(f"Task State: {response['task_state']}")

# COMMAND ----------

# DBTITLE 1,Test Calculator Agent
operations = [
    "Add 15 and 27",
    "Multiply 6 by 7",
    "Divide 100 by 4",
]

for op in operations:
    print(f"Request: {op}")
    response = asyncio.run(call_a2a_agent(CALC_AGENT_URL, op, AUTH_HEADERS))
    print(f"Result: {response['text']}")
    print(f"Task State: {response['task_state']}")
    print()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Task Lifecycle Management
# MAGIC
# MAGIC A2A supports async task management with `tasks/get` and `tasks/cancel`.

# COMMAND ----------

# DBTITLE 1,Task Lifecycle Demo
async def demo_task_lifecycle():
    """Demonstrate A2A task lifecycle: send, get status, complete."""
    print("═" * 60)
    print("A2A TASK LIFECYCLE DEMO")
    print("═" * 60)

    async with httpx.AsyncClient(timeout=60.0, headers=AUTH_HEADERS) as httpx_client:
        # Resolve agent card
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=CALC_AGENT_URL)
        card = await resolver.get_agent_card(http_kwargs={"headers": AUTH_HEADERS})

        if card.url and not card.url.startswith("http"):
            card.url = CALC_AGENT_URL.rstrip("/") + "/" + card.url.lstrip("/")

        client = A2AClient(httpx_client=httpx_client, agent_card=card)

        # Step 1: Send a message
        print("\n1. Sending message...")
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Multiply 123 by 456"))]
        )

        task_id = None
        final_task = None
        async for event in client.send_message(MessageSendParams(message=message)):
            if isinstance(event, tuple):
                task, update = event
                task_id = task.id
                final_task = task
                print(f"   Task ID: {task_id}")
                print(f"   State: {task.status.state.value if task.status else 'unknown'}")

        # Step 2: Get task status (if task completed quickly, this shows final state)
        if task_id:
            print("\n2. Getting task status...")
            try:
                task_status = await client.get_task(task_id)
                print(f"   Task ID: {task_status.id}")
                print(f"   State: {task_status.status.state.value if task_status.status else 'unknown'}")
                if task_status.artifacts:
                    result = extract_text_from_task(task_status)
                    print(f"   Result: {result}")
            except Exception as e:
                print(f"   Status check: {e}")

        # Step 3: Show final result
        print("\n3. Final result:")
        if final_task:
            result = extract_text_from_task(final_task)
            print(f"   {result}")

        print("\n" + "═" * 60)

asyncio.run(demo_task_lifecycle())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Streaming with A2A Client
# MAGIC
# MAGIC Stream responses in real-time using SSE.

# COMMAND ----------

# DBTITLE 1,Streaming Demo
async def stream_a2a_message(base_url: str, text: str, headers: dict = None):
    """Stream a message response from an A2A agent."""
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
        card = await resolver.get_agent_card(http_kwargs={"headers": headers} if headers else None)

        if card.url and not card.url.startswith("http"):
            card.url = base_url.rstrip("/") + "/" + card.url.lstrip("/")

        client = A2AClient(httpx_client=httpx_client, agent_card=card)

        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text=text))]
        )

        print("Streaming response:")
        print("-" * 40)

        async for event in client.send_message(MessageSendParams(message=message)):
            if isinstance(event, tuple):
                task, update = event
                state = task.status.state.value if task.status else "unknown"
                print(f"Task state: {state}")
                if task.artifacts:
                    result = extract_text_from_task(task)
                    if result:
                        print(f"Result: {result}")

        print("-" * 40)

print("Testing streaming with Calculator Agent:\n")
asyncio.run(stream_a2a_message(CALC_AGENT_URL, "What is 999 plus 1?", AUTH_HEADERS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Calling Agents via the Gateway
# MAGIC
# MAGIC The gateway proxies requests while enforcing UC connection access control.

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

# DBTITLE 1,Call Echo Agent via Gateway
print("Calling Echo Agent via Gateway...")
response = asyncio.run(call_agent_via_gateway(f"{PREFIX}-echo", "Hello via Gateway!"))
print(json.dumps(response, indent=2))

# COMMAND ----------

# DBTITLE 1,Call Calculator Agent via Gateway
print("Calling Calculator Agent via Gateway...")
response = asyncio.run(call_agent_via_gateway(f"{PREFIX}-calculator", "Multiply 7 by 8"))
print(json.dumps(response, indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Multi-Agent Workflow
# MAGIC
# MAGIC Orchestrate multiple agents using the A2A Client.

# COMMAND ----------

# DBTITLE 1,Multi-Agent Orchestration
async def multi_agent_workflow():
    """Demonstrate a workflow using multiple A2A agents."""
    print("═" * 60)
    print("MULTI-AGENT WORKFLOW")
    print("═" * 60)
    print()

    # Step 1: Test connectivity
    print("Step 1: Testing Echo Agent...")
    echo_result = await call_a2a_agent(ECHO_AGENT_URL, "System check", AUTH_HEADERS)
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
        result = await call_a2a_agent(CALC_AGENT_URL, expr, AUTH_HEADERS)
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

# DBTITLE 1,A2A Tool Pattern
from langchain_core.tools import tool

@tool
async def a2a_call(agent_url: str, message: str) -> str:
    """Call any A2A-compliant agent.

    Args:
        agent_url: The base URL of the A2A agent
        message: The message to send

    Returns:
        The agent's response
    """
    result = await call_a2a_agent(agent_url, message, AUTH_HEADERS)
    return result.get("text", "No response")

# Test the tool
print("Testing A2A tool pattern:")
result = asyncio.run(a2a_call.ainvoke({
    "agent_url": CALC_AGENT_URL,
    "message": "Add 100 and 200"
}))
print(f"Result: {result}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC | Feature | Method | Description |
# MAGIC |---------|--------|-------------|
# MAGIC | Agent Discovery | `A2ACardResolver` | Fetch agent cards |
# MAGIC | Send Message | `A2AClient.send_message()` | Sync/async messaging |
# MAGIC | Task Status | `A2AClient.get_task()` | Get task by ID |
# MAGIC | Streaming | SSE via `send_message()` | Real-time responses |
# MAGIC | Gateway Proxy | `POST /api/agents/{name}` | UC-governed access |
# MAGIC
# MAGIC ### Key Patterns
# MAGIC
# MAGIC 1. **Direct A2A** - Use `call_a2a_agent()` for direct agent communication
# MAGIC 2. **Gateway Proxy** - Use `call_agent_via_gateway()` for UC access control
# MAGIC 3. **Task Lifecycle** - Tasks have states: submitted → working → completed
# MAGIC 4. **Tool Pattern** - Wrap A2A client as LangChain tool for LLM orchestration

# COMMAND ----------

print("Demo complete!")
