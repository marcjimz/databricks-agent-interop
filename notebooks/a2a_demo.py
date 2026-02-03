# Databricks notebook source
# MAGIC %md
# MAGIC # A2A Protocol Demo Notebook
# MAGIC
# MAGIC This notebook demonstrates the **Agent-to-Agent (A2A) Protocol** using the official **A2A SDK Client**.
# MAGIC
# MAGIC **Features demonstrated:**
# MAGIC 1. **Agent Discovery** - Resolve agent cards via `A2ACardResolver`
# MAGIC 2. **A2A Client** - Send messages using `A2AClient`
# MAGIC 3. **Streaming** - Real-time SSE responses
# MAGIC 4. **Multi-Agent Orchestration** - Call multiple agents
# MAGIC
# MAGIC Reference: [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC
# MAGIC ### Configuration
# MAGIC
# MAGIC Default values are loaded from `notebooks/settings.yaml`. You can override any value using the widgets above.
# MAGIC
# MAGIC ### Getting an OAuth Token
# MAGIC
# MAGIC Databricks Apps require OAuth authentication. Run this command locally to get a token:
# MAGIC
# MAGIC ```bash
# MAGIC databricks auth token --host "${DATABRICKS_HOST}"
# MAGIC ```
# MAGIC
# MAGIC Copy the token and paste it into the **access_token** widget (or `settings.yaml` for persistence).
# MAGIC
# MAGIC > **Note:** Tokens expire after ~1 hour. If you get 401/302 errors, generate a new token.

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

# Load settings from YAML file to get defaults for widgets
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

# Create widgets with defaults from settings.yaml
dbutils.widgets.text("prefix", settings.get("prefix", "marcin"), "Agent Prefix")
dbutils.widgets.text("workspace_url_suffix", settings.get("workspace_url_suffix", "-1444828305810485.aws.databricksapps.com"), "Workspace URL Suffix")
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

# A2A SDK imports
from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.types import Message, Part, TextPart

# Get configuration from widgets (which have defaults from settings.yaml)
PREFIX = dbutils.widgets.get("prefix")
WORKSPACE_URL_SUFFIX = dbutils.widgets.get("workspace_url_suffix")
ACCESS_TOKEN = dbutils.widgets.get("access_token")

# Validate access token
if not ACCESS_TOKEN:
    raise ValueError(
        "access_token widget is empty!\n\n"
        "To get a token, run this command locally:\n"
        "  databricks auth token --host \"${DATABRICKS_HOST}\"\n\n"
        "Then paste the token into the 'access_token' widget above and re-run this cell.\n"
        "For persistence, add it to settings.yaml."
    )

# Build URLs from prefix and workspace suffix
GATEWAY_URL = f"https://{PREFIX}-a2a-gateway{WORKSPACE_URL_SUFFIX}"
ECHO_AGENT_URL = f"https://{PREFIX}-echo-agent{WORKSPACE_URL_SUFFIX}"
CALC_AGENT_URL = f"https://{PREFIX}-calculator-agent{WORKSPACE_URL_SUFFIX}"

# Build auth headers from the token
AUTH_HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

print(f"Gateway URL: {GATEWAY_URL}")
print(f"Echo Agent URL: {ECHO_AGENT_URL}")
print(f"Calculator Agent URL: {CALC_AGENT_URL}")
print(f"Auth Token: ✓ Configured ({len(ACCESS_TOKEN)} chars)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. A2A Agent Card Resolution
# MAGIC
# MAGIC The `A2ACardResolver` fetches and parses the agent card from `/.well-known/agent.json`.
# MAGIC Use `http_kwargs` to pass authentication headers for protected endpoints. If you get 302 below, double check your token.

# COMMAND ----------

# DBTITLE 1,Resolve Agent Cards with A2A SDK
async def resolve_agent_card(base_url: str, headers: dict = None):
    """Resolve an agent card using A2ACardResolver with proper auth headers.

    Args:
        base_url: The base URL of the A2A agent.
        headers: Optional dict of HTTP headers for authentication.

    Returns:
        The agent's AgentCard object.
    """
    # Build http_kwargs with headers
    http_kwargs = {}
    if headers:
        http_kwargs["headers"] = headers

    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        resolver = A2ACardResolver(httpx_client=client, base_url=base_url)
        # Pass auth headers via http_kwargs parameter
        card = await resolver.get_agent_card(http_kwargs=http_kwargs)
        return card

# Resolve the Gateway's agent card
print("═" * 60)
print("GATEWAY AGENT CARD")
print("═" * 60)
gateway_card = asyncio.run(resolve_agent_card(GATEWAY_URL, AUTH_HEADERS))
print(f"Name: {gateway_card.name}")
print(f"Description: {gateway_card.description}")
print(f"Version: {gateway_card.version}")
print(f"URL: {gateway_card.url}")
print(f"Capabilities: streaming={gateway_card.capabilities.streaming if gateway_card.capabilities else 'N/A'}")
print(f"Skills: {[s.name for s in gateway_card.skills] if gateway_card.skills else []}")

# COMMAND ----------

# DBTITLE 1,Resolve Echo Agent Card
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
print(f"Capabilities: streaming={calc_card.capabilities.streaming if calc_card.capabilities else 'N/A'}")
print(f"Skills:")
for skill in calc_card.skills or []:
    print(f"  • {skill.name}: {skill.description}")
    if skill.examples:
        print(f"    Examples: {skill.examples}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Send Messages with A2A Client
# MAGIC
# MAGIC The `ClientFactory` creates clients for JSON-RPC messaging with A2A agents.

# COMMAND ----------

# DBTITLE 1,A2A Client Helper
def extract_text_from_response(response) -> str:
    """Extract text from A2A response (handles both tuple and Message types).

    send_message() yields either:
    - tuple[Task, Update] where Task has artifacts
    - Message with parts
    """
    if response is None:
        return ""

    # Handle tuple (Task, Update) response
    if isinstance(response, tuple):
        task, update = response
        if task and task.artifacts:
            for artifact in task.artifacts:
                for part in artifact.parts:
                    if hasattr(part, 'root') and hasattr(part.root, 'text'):
                        return part.root.text
        return ""

    # Handle Message response
    if hasattr(response, 'parts'):
        for part in response.parts:
            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                return part.root.text
        return ""

    return str(response)


async def send_a2a_message(base_url: str, text: str, headers: dict = None) -> dict:
    """Send a message to an A2A agent using the official SDK ClientFactory.

    Returns a dict with 'text' (extracted response) and 'raw' (full response).
    """
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as httpx_client:
        # First resolve the agent card
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
        card = await resolver.get_agent_card(http_kwargs={"headers": headers} if headers else None)

        # Ensure card URL is absolute (SDK may use relative URL from card)
        if card.url and not card.url.startswith("http"):
            card.url = base_url.rstrip("/") + "/" + card.url.lstrip("/")

        # Create client config with httpx client
        config = ClientConfig(httpx_client=httpx_client)

        # Create client from the card with absolute URL
        factory = ClientFactory(config=config)
        client = factory.create(card=card)

        # Create Message object (new SDK API)
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text=text))]
        )

        # Send message - returns async iterator yielding (Task, Update) or Message
        final_task = None
        final_response = None
        async for event in client.send_message(message):
            if isinstance(event, tuple):
                task, update = event
                final_task = task  # Task accumulates state
            else:
                final_response = event

        # Extract text from response
        response_text = ""
        raw_response = None

        if final_task:
            raw_response = final_task.model_dump(mode="json")
            response_text = extract_text_from_response((final_task, None))
        elif final_response:
            raw_response = final_response.model_dump(mode="json") if hasattr(final_response, 'model_dump') else str(final_response)
            response_text = extract_text_from_response(final_response)

        return {
            "text": response_text,
            "raw": raw_response
        }

# COMMAND ----------

# MAGIC %md
# MAGIC ### Demo: Echo Agent with A2A Client

# COMMAND ----------

# DBTITLE 1,Test Echo Agent
print("Sending message to Echo Agent via A2A Client...")
print("-" * 40)

response = asyncio.run(send_a2a_message(
    ECHO_AGENT_URL,
    "Hello from the A2A SDK Client!",
    AUTH_HEADERS
))

print(f"Response text: {response['text']}")
print()
print("Raw response:")
print(json.dumps(response['raw'], indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Demo: Calculator Agent with A2A Client

# COMMAND ----------

# DBTITLE 1,Test Calculator Agent - Basic Operations
operations = [
    "Add 15 and 27",
    "Multiply 6 by 7",
    "Divide 100 by 4",
    "What is 25 times 4?"
]

for op in operations:
    print(f"Request: {op}")
    response = asyncio.run(send_a2a_message(CALC_AGENT_URL, op, AUTH_HEADERS))
    print(f"Result: {response['text']}")
    print()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Streaming with A2A Client
# MAGIC
# MAGIC The A2A SDK supports streaming responses via SSE using `send_message_streaming`.

# COMMAND ----------

# DBTITLE 1,Stream Messages with A2A Client
async def stream_a2a_message(base_url: str, text: str, headers: dict = None):
    """Stream a message response from an A2A agent using the SDK ClientFactory."""
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as httpx_client:
        # First resolve the agent card
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
        card = await resolver.get_agent_card(http_kwargs={"headers": headers} if headers else None)

        # Ensure card URL is absolute
        if card.url and not card.url.startswith("http"):
            card.url = base_url.rstrip("/") + "/" + card.url.lstrip("/")

        # Create client config with streaming enabled
        config = ClientConfig(httpx_client=httpx_client, streaming=True)

        # Create client from the card
        factory = ClientFactory(config=config)
        client = factory.create(card=card)

        # Create Message object (new SDK API)
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text=text))]
        )

        # Stream the response
        print("Streaming response:")
        print("-" * 40)

        async for event in client.send_message(message):
            # Handle different event types - can be (Task, Update) tuple or Message
            if isinstance(event, tuple):
                task, update = event
                if task:
                    print(f"Task state: {task.status.state if task.status else 'unknown'}")
                if update and hasattr(update, 'artifact'):
                    artifact = update.artifact
                    if artifact and artifact.parts:
                        for part in artifact.parts:
                            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                                print(f"Artifact: {part.root.text}")
            elif hasattr(event, 'parts'):
                # It's a Message response
                for part in event.parts:
                    if hasattr(part, 'root') and hasattr(part.root, 'text'):
                        print(f"Response: {part.root.text}")

        print("-" * 40)

# COMMAND ----------

# DBTITLE 1,Demo: Streaming with Echo Agent
print("Testing streaming with Echo Agent:\n")
asyncio.run(stream_a2a_message(ECHO_AGENT_URL, "This message is being streamed!", AUTH_HEADERS))

# COMMAND ----------

# DBTITLE 1,Demo: Streaming with Calculator Agent
print("Testing streaming with Calculator Agent:\n")
asyncio.run(stream_a2a_message(CALC_AGENT_URL, "What is 123 plus 456?", AUTH_HEADERS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Calling Agents via the Gateway
# MAGIC
# MAGIC The gateway proxies requests to downstream agents while enforcing UC connection access control.

# COMMAND ----------

# DBTITLE 1,Gateway Proxy Helper
async def call_agent_via_gateway(agent_name: str, text: str, headers: dict):
    """Call an agent through the A2A Gateway using raw HTTP (gateway proxy)."""
    # Merge auth headers with content-type
    request_headers = dict(headers) if headers else {}
    request_headers["Content-Type"] = "application/json"

    # Create A2A message
    message = {
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

    async with httpx.AsyncClient(timeout=60.0, headers=request_headers) as client:
        response = await client.post(
            f"{GATEWAY_URL}/api/agents/{agent_name}/message",
            json=message
        )
        response.raise_for_status()
        return response.json()

# COMMAND ----------

# DBTITLE 1,Call Echo Agent via Gateway
print("Calling Echo Agent via Gateway...")
response = asyncio.run(call_agent_via_gateway(f"{PREFIX}-echo", "Hello via Gateway!", AUTH_HEADERS))
print(json.dumps(response, indent=2))

# COMMAND ----------

# DBTITLE 1,Call Calculator Agent via Gateway
print("Calling Calculator Agent via Gateway...")
response = asyncio.run(call_agent_via_gateway(f"{PREFIX}-calculator", "Multiply 7 by 8", AUTH_HEADERS))
print(json.dumps(response, indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Multi-Agent Workflow
# MAGIC
# MAGIC Demonstrate orchestrating multiple agents using the A2A Client.

# COMMAND ----------

# DBTITLE 1,Multi-Agent Orchestration
async def multi_agent_workflow():
    """Demonstrate a workflow using multiple A2A agents."""
    print("═" * 60)
    print("MULTI-AGENT WORKFLOW USING A2A SDK")
    print("═" * 60)
    print()

    headers = AUTH_HEADERS

    async with httpx.AsyncClient(timeout=60.0, headers=headers) as httpx_client:
        # Create reusable client config and factory
        config = ClientConfig(httpx_client=httpx_client)
        factory = ClientFactory(config=config)

        # Step 1: Discover agents and create clients using ClientFactory
        print("Step 1: Discovering agents and creating clients...")

        clients = {}
        for name, url in [("echo", ECHO_AGENT_URL), ("calculator", CALC_AGENT_URL)]:
            # Resolve card and fix URL
            resolver = A2ACardResolver(httpx_client=httpx_client, base_url=url)
            card = await resolver.get_agent_card(http_kwargs={"headers": headers})
            if card.url and not card.url.startswith("http"):
                card.url = url.rstrip("/") + "/" + card.url.lstrip("/")
            client = factory.create(card=card)
            clients[name] = client
            print(f"  ✓ Connected to {name} agent")
        print()

        # Step 2: Test connectivity with Echo
        print("Step 2: Testing connectivity with Echo Agent...")
        echo_message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="System check: A2A active"))]
        )
        async for echo_response in clients["echo"].send_message(echo_message):
            pass  # Get final response
        print(f"  ✓ Echo responded successfully!")
        print()

        # Step 3: Perform calculations
        print("Step 3: Performing calculations with Calculator Agent...")
        calculations = [
            ("Revenue: 1250 * 12", "Multiply 1250 by 12"),
            ("Tax: 15000 * 0.25", "Multiply 15000 by 0.25"),
            ("Net: 15000 - 3750", "Subtract 3750 from 15000")
        ]

        for label, expr in calculations:
            calc_message = Message(
                messageId=str(uuid4()),
                role="user",
                parts=[Part(root=TextPart(text=expr))]
            )
            final_task = None
            async for event in clients["calculator"].send_message(calc_message):
                if isinstance(event, tuple):
                    task, update = event
                    final_task = task

            # Extract result using helper function
            result_text = extract_text_from_response((final_task, None)) if final_task else "N/A"
            print(f"  {label} = {result_text}")
        print()

        # Step 4: Summary
        print("Step 4: Workflow complete!")
        print("  ✓ Connected to 2 agents via ClientFactory")
        print("  ✓ Verified connectivity")
        print("  ✓ Performed 3 calculations")
        print()
        print("═" * 60)

asyncio.run(multi_agent_workflow())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. A2A Client as a Tool (Agent Interoperability)
# MAGIC
# MAGIC This pattern shows how to wrap the A2A client as a LangChain tool, enabling an LLM-powered agent to call other A2A agents.

# COMMAND ----------

# DBTITLE 1,A2A Client as LangChain Tool
from langchain_core.tools import tool

@tool
async def call_a2a_agent(agent_url: str, message: str) -> str:
    """Call any A2A-compliant agent and get a response.

    Args:
        agent_url: The base URL of the A2A agent (e.g., https://agent.example.com)
        message: The message to send to the agent

    Returns:
        The agent's response as a string
    """
    headers = AUTH_HEADERS

    async with httpx.AsyncClient(timeout=60.0, headers=headers) as httpx_client:
        # Resolve card and fix URL
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=agent_url)
        card = await resolver.get_agent_card(http_kwargs={"headers": headers})
        if card.url and not card.url.startswith("http"):
            card.url = agent_url.rstrip("/") + "/" + card.url.lstrip("/")

        # Create client using ClientFactory
        config = ClientConfig(httpx_client=httpx_client)
        factory = ClientFactory(config=config)
        client = factory.create(card=card)

        # Create Message object (new SDK API)
        msg = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text=message))]
        )

        # Iterate through async iterator - collect final task
        final_task = None
        async for event in client.send_message(msg):
            if isinstance(event, tuple):
                task, update = event
                final_task = task

        # Extract text using helper function
        if final_task:
            return extract_text_from_response((final_task, None)) or json.dumps({"error": "No text response"})

        return json.dumps({"error": "No response"})

# Test the tool
print("Testing A2A Client as a LangChain tool:")
result = asyncio.run(call_a2a_agent.ainvoke({
    "agent_url": CALC_AGENT_URL,
    "message": "Add 100 and 200"
}))
print(f"Result: {result}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC This notebook demonstrated A2A interoperability using the official SDK:
# MAGIC
# MAGIC | Component | Class/Method | Purpose |
# MAGIC |-----------|--------------|---------|
# MAGIC | `A2ACardResolver` | Agent discovery | Fetch and parse agent cards |
# MAGIC | `ClientFactory` | Client creation | Create clients with JSON-RPC transport |
# MAGIC | `ClientConfig` | Configuration | Configure httpx client and streaming |
# MAGIC | `SendMessageRequest` | Request format | Proper JSON-RPC structure |
# MAGIC | `send_message()` | Sync call | Get complete response |
# MAGIC | `send_message_streaming()` | SSE streaming | Real-time responses |
# MAGIC
# MAGIC ### Key Takeaways
# MAGIC
# MAGIC 1. **Use the A2A SDK** - Don't build raw HTTP calls; use `ClientFactory.connect()` for clients
# MAGIC 2. **Agent cards are key** - They describe capabilities and enable discovery
# MAGIC 3. **Interoperability** - Any A2A-compliant agent can communicate with any other
# MAGIC 4. **Tool pattern** - Wrap A2A client as a tool for LLM-powered orchestration
# MAGIC 5. **Gateway for governance** - Use the gateway for UC-based access control

# COMMAND ----------

print("Demo complete!")
