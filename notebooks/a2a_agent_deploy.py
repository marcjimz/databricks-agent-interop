# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy A2A Orchestrator Agent to Mosaic AI Framework
# MAGIC
# MAGIC This notebook deploys an **A2A-interoperable agent** to Databricks Mosaic AI Framework using `agents.deploy()`.
# MAGIC
# MAGIC The agent:
# MAGIC - Is **discoverable** via Mosaic AI Model Serving endpoint
# MAGIC - Can **discover** other A2A agents via the A2A Gateway
# MAGIC - Can **call** other A2A agents using the official A2A SDK
# MAGIC
# MAGIC **Deployment Flow:**
# MAGIC 1. Build agent with LangChain/LangGraph + A2A SDK tools
# MAGIC 2. Log to MLflow (models-from-code pattern)
# MAGIC 3. Register to Unity Catalog
# MAGIC 4. Deploy with `agents.deploy()`
# MAGIC
# MAGIC Reference: [Deploy an Agent](https://learn.microsoft.com/en-us/azure/databricks/generative-ai/agent-framework/deploy-agent)

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
# MAGIC %pip install mlflow>=3.1.0 databricks-agents>=0.12.0 langchain>=0.3.0 langchain-core>=0.3.0 langgraph>=0.2.0 databricks-langchain>=0.1.0 a2a-sdk[http-server]>=0.3.0 httpx nest_asyncio pyyaml --quiet

# COMMAND ----------

# DBTITLE 1,Restart Python
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
dbutils.widgets.text("catalog", settings.get("catalog", "main"), "Catalog Name")
dbutils.widgets.text("schema", settings.get("schema", "default"), "Schema Name")
dbutils.widgets.text("foundation_model", settings.get("foundation_model", "databricks-meta-llama-3-1-8b-instruct"), "Foundation Model")
dbutils.widgets.text("access_token", settings.get("access_token", ""), "OAuth Access Token")

# COMMAND ----------

# DBTITLE 1,Configuration
import mlflow
from databricks import agents
from databricks.sdk import WorkspaceClient
from datetime import datetime
import json

# Enable nested event loops (required for Databricks notebooks)
import nest_asyncio
nest_asyncio.apply()

# Initialize Databricks client
w = WorkspaceClient()

# Get configuration from widgets (which have defaults from settings.yaml)
PREFIX = dbutils.widgets.get("prefix")
WORKSPACE_URL_SUFFIX = dbutils.widgets.get("workspace_url_suffix")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
FOUNDATION_MODEL = dbutils.widgets.get("foundation_model")
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

# Build auth headers from the token
AUTH_HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

# Get current user
username = spark.sql("SELECT current_user()").first()[0]
normalized_username = username.split('@')[0].replace('.', '_')

# Build URLs from prefix and workspace suffix
GATEWAY_URL = f"https://{PREFIX}-a2a-gateway{WORKSPACE_URL_SUFFIX}"
ECHO_AGENT_URL = f"https://{PREFIX}-echo-agent{WORKSPACE_URL_SUFFIX}"
CALC_AGENT_URL = f"https://{PREFIX}-calculator-agent{WORKSPACE_URL_SUFFIX}"

# Unity Catalog model name
AGENT_NAME = "a2a_orchestrator_agent"
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.{AGENT_NAME}_{normalized_username}"

print(f"✅ Configuration loaded")
print(f"📍 Unity Catalog Model: {UC_MODEL_NAME}")
print(f"👤 User: {username}")
print(f"🤖 Foundation Model: {FOUNDATION_MODEL}")
print(f"🌐 Gateway URL: {GATEWAY_URL}")
print(f"🔑 Auth Token: ✓ Configured ({len(ACCESS_TOKEN)} chars)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Create MLflow Experiment

# COMMAND ----------

# DBTITLE 1,Setup MLflow Experiment
EXPERIMENT_NAME = f"/Users/{username}/a2a-orchestrator-deployment_{normalized_username}"

print(f"🔬 Setting up MLflow experiment...\n")

try:
    experiment_id = mlflow.create_experiment(
        name=EXPERIMENT_NAME,
        tags={
            "project": "a2a_orchestrator",
            "use_case": "agent_interoperability",
            "created_by": username,
            "created_at": datetime.now().isoformat()
        }
    )
    print(f"✅ Created new experiment: {EXPERIMENT_NAME}")
except Exception as e:
    experiment = mlflow.get_experiment_by_name(EXPERIMENT_NAME)
    experiment_id = experiment.experiment_id
    print(f"✅ Using existing experiment: {EXPERIMENT_NAME}")

mlflow.set_experiment(experiment_name=EXPERIMENT_NAME)
print(f"   Experiment ID: {experiment_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Build the A2A Orchestrator Agent
# MAGIC
# MAGIC The agent uses LangGraph with tools that leverage the official A2A SDK.

# COMMAND ----------

# DBTITLE 1,Build Agent with A2A Tools
from databricks_langchain import ChatDatabricks
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent
from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.types import Message, Part, TextPart
from uuid import uuid4
import httpx
import asyncio


def extract_text_from_response(response) -> str:
    """Extract text from A2A response (handles both tuple and Message types)."""
    if response is None:
        return ""
    if isinstance(response, tuple):
        task, update = response
        if task and task.artifacts:
            for artifact in task.artifacts:
                for part in artifact.parts:
                    if hasattr(part, 'root') and hasattr(part.root, 'text'):
                        return part.root.text
        return ""
    if hasattr(response, 'parts'):
        for part in response.parts:
            if hasattr(part, 'root') and hasattr(part.root, 'text'):
                return part.root.text
        return ""
    return str(response)


print("🏗️ Building A2A Orchestrator Agent...\n")

# Note: AUTH_HEADERS is defined in the Configuration section above
# from the access_token widget

# Initialize the foundation model
llm = ChatDatabricks(
    endpoint=FOUNDATION_MODEL,
    temperature=0.1,
    max_tokens=1000
)

# System prompt
SYSTEM_PROMPT = """You are an A2A Orchestrator Agent that can discover and communicate with other A2A-compliant agents.

You have access to tools that let you:
1. Discover available agents via the A2A Gateway
2. Get details about any A2A agent's capabilities (agent card)
3. Call any A2A agent to perform tasks

When a user asks you to do something:
1. First, determine if you need to use another agent
2. If needed, discover available agents or get their capabilities
3. Call the appropriate agent with the right message
4. Return the result to the user

Available agents typically include:
- Echo Agent: Echoes back messages (useful for testing connectivity)
- Calculator Agent: Performs arithmetic operations (add, subtract, multiply, divide)

Be helpful and concise. When you receive results from other agents, summarize them clearly for the user.
"""

# Define A2A tools
@tool
def discover_agents() -> str:
    """Discover available A2A agents via the gateway.

    Returns a list of available agents with their names and descriptions.
    Use this when you need to know what agents are available.
    """
    headers = AUTH_HEADERS

    try:
        with httpx.Client(timeout=30.0, headers=headers) as client:
            response = client.get(f"{GATEWAY_URL}/api/agents")
            response.raise_for_status()
            data = response.json()

            agents_list = data.get("agents", [])
            if not agents_list:
                return "No agents found"

            result = f"Found {len(agents_list)} agents:\n"
            for agent in agents_list:
                result += f"- {agent['name']}: {agent.get('description', 'No description')}\n"
                result += f"  URL: {agent.get('agent_card_url', 'N/A')}\n"

            return result
    except Exception as e:
        return f"Error discovering agents: {str(e)}"


@tool
def get_agent_capabilities(agent_url: str) -> str:
    """Get the capabilities of an A2A agent by fetching its agent card.

    Args:
        agent_url: The base URL of the A2A agent

    Returns:
        A description of the agent's capabilities and skills.
    """
    headers = AUTH_HEADERS
    http_kwargs = {"headers": headers} if headers else {}

    async def _get_card():
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            resolver = A2ACardResolver(httpx_client=client, base_url=agent_url)
            return await resolver.get_agent_card(http_kwargs=http_kwargs)

    try:
        card = asyncio.run(_get_card())

        result = f"Agent: {card.name}\n"
        result += f"Description: {card.description}\n"

        if card.skills:
            result += "Skills:\n"
            for skill in card.skills:
                result += f"  - {skill.name}: {skill.description}\n"

        return result
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def call_a2a_agent(agent_url: str, message: str) -> str:
    """Call an A2A-compliant agent using the official A2A SDK.

    Args:
        agent_url: The base URL of the A2A agent
        message: The message to send to the agent

    Returns:
        The agent's response as a string
    """
    headers = AUTH_HEADERS

    async def _call():
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
                return extract_text_from_response((final_task, None)) or "No text response"
            return "No response"

    try:
        return asyncio.run(_call())
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def call_agent_via_gateway(agent_name: str, message: str) -> str:
    """Call an agent through the A2A Gateway by name.

    The gateway enforces UC connection access control.

    Args:
        agent_name: The short name of the agent (e.g., 'marcin-echo')
        message: The message to send

    Returns:
        The agent's response
    """
    # Merge auth headers with content-type
    headers = dict(AUTH_HEADERS) if AUTH_HEADERS else {}
    headers["Content-Type"] = "application/json"

    a2a_message = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid4()),
                "role": "user",
                "parts": [{"kind": "text", "text": message}]
            }
        }
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{GATEWAY_URL}/api/agents/{agent_name}/message",
                json=a2a_message,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()

            # Extract result
            result = data.get("result", {})
            for artifact in result.get("artifacts", []):
                for part in artifact.get("parts", []):
                    if part.get("kind") == "text":
                        return part.get("text", "")

            return json.dumps(data)
    except Exception as e:
        return f"Error: {str(e)}"

# Create the agent
tools = [discover_agents, get_agent_capabilities, call_a2a_agent, call_agent_via_gateway]
agent = create_react_agent(llm, tools)

print(f"✅ A2A Orchestrator Agent created")
print(f"   Foundation Model: {FOUNDATION_MODEL}")
print(f"   Tools: {[t.name for t in tools]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Test the Agent Locally

# COMMAND ----------

# DBTITLE 1,Test: Discover Agents
print("🧪 Test 1: Discover available agents\n")

response = agent.invoke({
    "messages": [
        SystemMessage(content=SYSTEM_PROMPT),
        {"role": "user", "content": "What agents are available?"}
    ]
})

print(response["messages"][-1].content)

# COMMAND ----------

# DBTITLE 1,Test: Call Calculator via Gateway
print("🧪 Test 2: Call calculator agent\n")

response = agent.invoke({
    "messages": [
        SystemMessage(content=SYSTEM_PROMPT),
        {"role": "user", "content": f"Use the calculator agent ({PREFIX}-calculator) to add 42 and 58"}
    ]
})

print(response["messages"][-1].content)

# COMMAND ----------

# DBTITLE 1,Test: Multi-Agent Workflow
print("🧪 Test 3: Multi-agent workflow\n")

response = agent.invoke({
    "messages": [
        SystemMessage(content=SYSTEM_PROMPT),
        {"role": "user", "content": f"First test connectivity by echoing 'Hello' using {PREFIX}-echo, then calculate 100 times 25 using {PREFIX}-calculator"}
    ]
})

print(response["messages"][-1].content)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Log Agent to MLflow
# MAGIC
# MAGIC Using the MLflow 3.x "models from code" pattern.

# COMMAND ----------

# DBTITLE 1,Log Agent to MLflow
print("📦 Logging agent to MLflow...\n")

# Model configuration
model_config = {
    "foundation_model_endpoint": FOUNDATION_MODEL,
    "temperature": 0.1,
    "max_tokens": 1000,
    "gateway_url": GATEWAY_URL,
    # Note: auth_token should be injected at runtime via service principal
    # For now, we'll document this requirement
}

# Input example
input_example = {
    "messages": [
        {"role": "user", "content": "What agents are available?"}
    ]
}

# Generate test output for signature inference
print("🔍 Generating test output for signature inference...")
test_response = agent.invoke({
    "messages": [
        SystemMessage(content=SYSTEM_PROMPT),
        {"role": "user", "content": "What agents are available?"}
    ]
})

test_output = {
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": test_response["messages"][-1].content
            },
            "finish_reason": "stop"
        }
    ]
}

# Infer signature
signature = mlflow.models.infer_signature(
    model_input=input_example,
    model_output=test_output
)

print(f"✅ Signature inferred")

# Log the model
model_info = mlflow.pyfunc.log_model(
    artifact_path="agent",
    python_model="../src/agents/orchestrator/a2a_orchestrator_model.py",
    model_config=model_config,
    input_example=input_example,
    signature=signature,
    pip_requirements=[
        "mlflow>=3.1.0",
        "langchain>=0.3.0",
        "langchain-core>=0.3.0",
        "langgraph>=0.2.0",
        "databricks-langchain>=0.1.0",
        "a2a-sdk[http-server]>=0.3.0",
        "httpx>=0.27.0",
    ]
)

run_id = model_info.run_id
model_uri = model_info.model_uri

# Log additional metadata
with mlflow.start_run(run_id=run_id):
    mlflow.log_param("foundation_model", FOUNDATION_MODEL)
    mlflow.log_param("num_tools", len(tools))
    mlflow.log_param("gateway_url", GATEWAY_URL)
    mlflow.log_param("pattern", "models-from-code")

    mlflow.set_tag("agent_type", "a2a_orchestrator")
    mlflow.set_tag("interoperable", "true")
    mlflow.set_tag("a2a_compliant", "true")
    mlflow.set_tag("created_by", username)

print(f"\n✅ Agent logged to MLflow")
print(f"   Run ID: {run_id}")
print(f"   Model URI: {model_uri}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Register to Unity Catalog

# COMMAND ----------

# DBTITLE 1,Register Model to Unity Catalog
print(f"📝 Registering agent to Unity Catalog...\n")

uc_model_info = mlflow.register_model(
    model_uri=model_uri,
    name=UC_MODEL_NAME,
    tags={
        "task": "a2a_orchestration",
        "framework": "langgraph",
        "interoperable": "true",
        "foundation_model": FOUNDATION_MODEL
    }
)

model_version = uc_model_info.version

print(f"✅ Agent registered to Unity Catalog")
print(f"   Model Name: {UC_MODEL_NAME}")
print(f"   Version: {model_version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Deploy with `agents.deploy()`
# MAGIC
# MAGIC This creates a Model Serving endpoint with:
# MAGIC - Autoscaling infrastructure
# MAGIC - Review App for testing
# MAGIC - Inference tables for logging
# MAGIC - Real-time tracing (MLflow 3.0+)

# COMMAND ----------

# DBTITLE 1,Deploy to Mosaic AI
from databricks import agents

print(f"🚀 Deploying agent to Mosaic AI Framework...\n")
print(f"   Model: {UC_MODEL_NAME}")
print(f"   Version: {model_version}")
print(f"   ⏰ This may take 10-15 minutes...\n")

deployment = agents.deploy(
    model_name=UC_MODEL_NAME,
    model_version=model_version,
    scale_to_zero_enabled=True  # Cost optimization
)

endpoint_name = deployment.endpoint_name
query_endpoint = deployment.query_endpoint

print(f"\n✅ Agent deployed successfully!")
print(f"\n📍 Deployment Details:")
print(f"   • Endpoint Name: {endpoint_name}")
print(f"   • Query Endpoint: {query_endpoint}")
print(f"   • Model: {UC_MODEL_NAME} (v{model_version})")

print(f"\n🔧 Automatically Enabled Features:")
print(f"   ✓ Model Serving endpoint with autoscaling")
print(f"   ✓ Review App for stakeholder feedback")
print(f"   ✓ Inference tables for logging")
print(f"   ✓ Real-time tracing (MLflow 3.0+)")

print(f"\n💡 Next Steps:")
print(f"   1. Test the endpoint (next cell)")
print(f"   2. Access Review App: Compute > Serving > {endpoint_name}")
print(f"   3. Register as A2A agent via UC connection for full interoperability")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Test the Deployed Endpoint

# COMMAND ----------

# DBTITLE 1,Query the Deployed Agent
import time

print("⏳ Waiting for endpoint to warm up...")
time.sleep(30)  # Give endpoint time to warm up

print("\n🧪 Testing deployed endpoint...\n")

# Query using the deployment endpoint
try:
    response = w.serving_endpoints.query(
        name=endpoint_name,
        messages=[
            {"role": "user", "content": "What agents can you discover?"}
        ]
    )

    print("✅ Response from deployed agent:")
    print("-" * 40)
    if hasattr(response, 'choices') and response.choices:
        print(response.choices[0].message.content)
    else:
        print(response)
except Exception as e:
    print(f"⚠️ Endpoint may still be warming up. Error: {e}")
    print(f"\nTry again in a few minutes, or test via the Review App.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Register as A2A Agent (Optional)
# MAGIC
# MAGIC To make this deployed agent **discoverable via the A2A Gateway**, create a UC connection:
# MAGIC
# MAGIC ```bash
# MAGIC # Get the endpoint URL
# MAGIC ORCHESTRATOR_URL="https://<workspace>.cloud.databricks.com/serving-endpoints/<endpoint-name>/invocations"
# MAGIC
# MAGIC # Create UC connection
# MAGIC databricks connections create --json '{
# MAGIC   "name": "orchestrator-a2a",
# MAGIC   "connection_type": "HTTP",
# MAGIC   "options": {
# MAGIC     "host": "<orchestrator-base-url>",
# MAGIC     "base_path": "/.well-known/agent.json",
# MAGIC     "bearer_token": "databricks"
# MAGIC   },
# MAGIC   "comment": "A2A Orchestrator Agent"
# MAGIC }'
# MAGIC ```
# MAGIC
# MAGIC **Note:** Model Serving endpoints don't natively serve `/.well-known/agent.json`.
# MAGIC For full A2A interoperability, consider:
# MAGIC 1. Deploying a thin FastAPI wrapper that serves the agent card
# MAGIC 2. Using Databricks Apps for the A2A-compliant wrapper
# MAGIC 3. Registering the Model Serving endpoint directly with custom routing

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC This notebook deployed an **A2A-interoperable orchestrator agent** to Mosaic AI Framework:
# MAGIC
# MAGIC | Component | Description |
# MAGIC |-----------|-------------|
# MAGIC | **Agent** | LangGraph ReAct agent with A2A SDK tools |
# MAGIC | **Tools** | `discover_agents`, `get_agent_capabilities`, `call_a2a_agent`, `call_agent_via_gateway` |
# MAGIC | **Registry** | Unity Catalog model: `{UC_MODEL_NAME}` |
# MAGIC | **Endpoint** | Model Serving with autoscaling |
# MAGIC | **Features** | Review App, inference tables, tracing |
# MAGIC
# MAGIC ### Key Capabilities
# MAGIC
# MAGIC 1. **Discoverable** - Deployed to Mosaic AI Model Serving
# MAGIC 2. **Interoperable** - Can call other A2A agents via the official SDK
# MAGIC 3. **Governed** - Access controlled via Unity Catalog
# MAGIC 4. **Observable** - Inference tables and MLflow tracing
# MAGIC
# MAGIC ### Architecture
# MAGIC
# MAGIC ```
# MAGIC User → Model Serving Endpoint → A2A Orchestrator Agent
# MAGIC                                         │
# MAGIC                                         ├── discover_agents() → A2A Gateway
# MAGIC                                         ├── call_a2a_agent() → Any A2A Agent
# MAGIC                                         └── call_agent_via_gateway() → Gateway → UC Access Control → Agent
# MAGIC ```

# COMMAND ----------

print("🎉 Deployment complete!")
print(f"\nEndpoint: {endpoint_name}")
print(f"Model: {UC_MODEL_NAME}")
