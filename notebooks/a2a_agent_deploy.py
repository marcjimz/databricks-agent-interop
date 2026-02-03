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
# MAGIC ### OBO Authentication
# MAGIC
# MAGIC This notebook deploys an agent with **OBO (On-Behalf-Of) authentication**. When deployed:
# MAGIC - The agent uses the **calling user's identity** to access the A2A Gateway
# MAGIC - No OAuth tokens need to be configured in advance
# MAGIC - Access control is enforced via Unity Catalog permissions

# COMMAND ----------

# DBTITLE 1,Install Dependencies
# MAGIC %pip install -r requirements.txt --quiet

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
dbutils.widgets.text("catalog", settings.get("catalog", "main"), "Catalog Name")
dbutils.widgets.text("schema", settings.get("schema", "default"), "Schema Name")
dbutils.widgets.text("foundation_model", settings.get("foundation_model", "databricks-meta-llama-3-1-8b-instruct"), "Foundation Model")
dbutils.widgets.text("agent_name", settings.get("agent_name", "a2a_orchestrator"), "Agent Name")
dbutils.widgets.text("experiment_name", settings.get("experiment_name", "a2a-orchestrator-deployment"), "Experiment Name")
dbutils.widgets.text("endpoint_name", settings.get("endpoint_name", "a2a_orchestrator"), "Endpoint Name")

# COMMAND ----------

# DBTITLE 1,Configuration
import mlflow
from databricks import agents
from databricks.sdk import WorkspaceClient
from datetime import datetime

# Initialize Databricks client
w = WorkspaceClient()

# Get configuration from widgets (which have defaults from settings.yaml)
PREFIX = dbutils.widgets.get("prefix")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
FOUNDATION_MODEL = dbutils.widgets.get("foundation_model")
AGENT_NAME = dbutils.widgets.get("agent_name")
EXPERIMENT_BASE_NAME = dbutils.widgets.get("experiment_name")
ENDPOINT_BASE_NAME = dbutils.widgets.get("endpoint_name")

# Get current user
username = spark.sql("SELECT current_user()").first()[0]
normalized_username = username.split('@')[0].replace('.', '_')

# Get gateway URL dynamically from the Databricks App
GATEWAY_APP_NAME = f"{PREFIX}-a2a-gateway"
try:
    gateway_app = w.apps.get(name=GATEWAY_APP_NAME)
    GATEWAY_URL = gateway_app.url
    print(f"✅ Found gateway app: {GATEWAY_APP_NAME}")
except Exception as e:
    raise ValueError(
        f"Could not find gateway app '{GATEWAY_APP_NAME}'. "
        f"Make sure the A2A Gateway is deployed first with 'make deploy PREFIX={PREFIX}'. "
        f"Error: {e}"
    )

# Derived names
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.{AGENT_NAME}_{normalized_username}"
EXPERIMENT_NAME = f"/Users/{username}/{EXPERIMENT_BASE_NAME}_{normalized_username}"
ENDPOINT_NAME = f"{PREFIX}-{ENDPOINT_BASE_NAME}"

print(f"✅ Configuration loaded")
print(f"📍 Unity Catalog Model: {UC_MODEL_NAME}")
print(f"🔬 Experiment: {EXPERIMENT_NAME}")
print(f"🚀 Endpoint: {ENDPOINT_NAME}")
print(f"👤 User: {username}")
print(f"🤖 Foundation Model: {FOUNDATION_MODEL}")
print(f"🌐 Gateway URL: {GATEWAY_URL}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Create MLflow Experiment

# COMMAND ----------

# DBTITLE 1,Setup MLflow Experiment
print(f"🔬 Setting up MLflow experiment: {EXPERIMENT_NAME}\n")

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
# MAGIC ## 2. Log Agent to MLflow
# MAGIC
# MAGIC Using the MLflow 3.x "models from code" pattern with **OBO (On-Behalf-Of) authentication**.
# MAGIC
# MAGIC ### OBO Authentication
# MAGIC
# MAGIC The agent uses OBO auth to act on behalf of the user making the request. This enables:
# MAGIC - Fine-grained access control via Unity Catalog
# MAGIC - Per-user permissions when calling the A2A Gateway
# MAGIC - Secure agent-to-agent communication with caller's identity
# MAGIC
# MAGIC **Requirement:** A workspace admin must enable OBO for AI agents. See [Agent Authentication](https://docs.databricks.com/aws/en/generative-ai/agent-framework/agent-authentication).

# COMMAND ----------

# DBTITLE 1,Log Agent to MLflow (ResponsesAgent Pattern)
from mlflow.models.auth_policy import AuthPolicy, SystemAuthPolicy, UserAuthPolicy
from mlflow.models.resources import DatabricksServingEndpoint
from pkg_resources import get_distribution
import os
import tempfile

print("📦 Logging agent to MLflow using ResponsesAgent pattern...\n")

# System Auth Policy - for resources accessed by the service principal
# This allows the agent to call the foundation model endpoint
resources = [DatabricksServingEndpoint(endpoint_name=FOUNDATION_MODEL)]
system_auth_policy = SystemAuthPolicy(resources=resources)

# User Auth Policy - OBO scopes for acting as the end user
# This enables the agent to call APIs using the caller's identity
user_auth_policy = UserAuthPolicy(
    api_scopes=[
        "apps.apps",  # For calling Databricks Apps (A2A Gateway)
        "catalog.connections",  # For accessing UC connections via the gateway
        "iam.access-control:read",  # For reading access control policies
        "iam.current-user:read",  # For reading current user identity
        "mcp.external",  # For MCP external tool access
        "mcp.functions",  # For MCP function access
    ]
)

# Combined Auth Policy - both system and user auth
# - System: service principal access to LLM endpoint
# - User: OBO access to apps.apps API
auth_policy = AuthPolicy(
    system_auth_policy=system_auth_policy,
    user_auth_policy=user_auth_policy
)

print("🔐 Auth Policy configured:")
print(f"   System resources: [{FOUNDATION_MODEL}]")
print(f"   User scopes (OBO): {user_auth_policy.api_scopes}")

# Find the orchestrator agent file from the bundle
# The agent is defined in src/agents/orchestrator/a2a_orchestrator_model.py
possible_agent_paths = [
    Path("/Workspace/Users") / spark.sql("SELECT current_user()").first()[0] / ".bundle/a2a-gateway/dev/files/src/agents/orchestrator/a2a_orchestrator_model.py",
    Path("../src/agents/orchestrator/a2a_orchestrator_model.py"),
    Path("src/agents/orchestrator/a2a_orchestrator_model.py"),
]

agent_file_path = None
for path in possible_agent_paths:
    try:
        if path.exists():
            agent_file_path = str(path)
            print(f"Found agent file: {agent_file_path}")
            break
    except Exception:
        continue

if not agent_file_path:
    raise FileNotFoundError(
        "Could not find a2a_orchestrator_model.py. Searched paths:\n" +
        "\n".join(f"  - {p}" for p in possible_agent_paths)
    )

print(f"✅ Using agent file: {agent_file_path}")

# Log the model with OBO auth policy using MLflow 3.x ResponsesAgent pattern
with mlflow.start_run() as run:
    run_id = run.info.run_id

    model_info = mlflow.pyfunc.log_model(
        name="agent",
        python_model=agent_file_path,  # Use the orchestrator agent file from src/
        auth_policy=auth_policy,
        pip_requirements=[
            "backoff",
            "mlflow>=3.8.0",
            "langchain>=1.0.0",
            "langchain-core>=1.0.0",
            "langgraph>=1.0.0",
            "databricks-langchain>=0.13.0",
            "databricks-sdk>=0.78.0",
            "databricks-ai-bridge>=0.10.0",
            "a2a-sdk>=0.3.20",
            "httpx>=0.28.0",
            f"databricks-connect=={get_distribution('databricks-connect').version}"
        ]
    )

    model_uri = model_info.model_uri

    mlflow.log_param("foundation_model", FOUNDATION_MODEL)
    mlflow.log_param("gateway_url", GATEWAY_URL)
    mlflow.log_param("num_tools", 2)  # discover_agents, call_agent
    mlflow.log_param("pattern", "responses-agent")
    mlflow.log_param("auth_method", "obo")

    mlflow.set_tag("agent_type", "a2a_orchestrator")
    mlflow.set_tag("interoperable", "true")
    mlflow.set_tag("a2a_compliant", "true")
    mlflow.set_tag("uses_obo", "true")
    mlflow.set_tag("uses_responses_agent", "true")
    mlflow.set_tag("created_by", username)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Register to Unity Catalog

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
# MAGIC ## 4. Deploy with `agents.deploy()`
# MAGIC
# MAGIC This creates a Model Serving endpoint with:
# MAGIC - Autoscaling infrastructure
# MAGIC - Review App for testing
# MAGIC - Inference tables for logging
# MAGIC - Real-time tracing (MLflow 3.0+)
# MAGIC
# MAGIC ### OBO Permissions Required
# MAGIC
# MAGIC For the agent to call the A2A Gateway, the **calling user** must have:
# MAGIC 1. `CAN_QUERY` permission on the A2A Gateway Databricks App
# MAGIC 2. `USE_CONNECTION` on any UC connections the gateway uses
# MAGIC
# MAGIC If you see **401 Unauthorized** errors when calling agents:
# MAGIC - Grant the user `CAN_QUERY` on the gateway app: `databricks apps update-permissions <app-name> --level CAN_QUERY --user-name <user>`
# MAGIC - Grant `USE_CONNECTION` on relevant UC connections

# COMMAND ----------

# DBTITLE 1,Deploy to Mosaic AI
from databricks import agents

print(f"🚀 Deploying agent to Mosaic AI Framework...\n")
print(f"   Model: {UC_MODEL_NAME}")
print(f"   Version: {model_version}")
print(f"   Endpoint: {ENDPOINT_NAME}")
print(f"   ⏰ This may take 10-15 minutes...\n")

ENVIRONMENT_VARS = {
    "GATEWAY_URL": GATEWAY_URL,
    "FOUNDATION_MODEL_ENDPOINT": FOUNDATION_MODEL,
    "TEMPERATURE": "0.1",
    "MAX_TOKENS": "1000"
}

deployment = agents.deploy(
    endpoint_name=ENDPOINT_NAME,
    model_name=UC_MODEL_NAME,
    model_version=model_version,
    environment_vars=ENVIRONMENT_VARS,  # Pass config as env vars
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
# MAGIC ## 5. Test the Deployed Endpoint (OBO Works Here!)
# MAGIC
# MAGIC **This is where OBO actually works.** When you query the deployed endpoint:
# MAGIC - `ModelServingUserCredentials()` extracts YOUR identity from the request
# MAGIC - The agent calls the A2A Gateway using YOUR credentials
# MAGIC - The gateway checks YOUR permissions on UC connections
# MAGIC
# MAGIC If you still get 401 errors here, check:
# MAGIC 1. You have `CAN_QUERY` permission on the A2A Gateway app
# MAGIC 2. The endpoint logs show `OAUTH TOKEN SIZE: 500+` (not 43)

# COMMAND ----------

# DBTITLE 1,Query the Deployed Agent (OBO-enabled)
import time
from databricks.sdk.service.serving import EndpointStateReady

def wait_for_endpoint_ready(client, endpoint_name, expected_model_name, expected_version, timeout_minutes=15, poll_interval_seconds=30):
    """Wait for serving endpoint to be ready AND serving the expected model version."""
    print(f"⏳ Waiting for endpoint '{endpoint_name}' to be ready...")
    print(f"   Expected: {expected_model_name} v{expected_version}")

    timeout_seconds = timeout_minutes * 60
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            raise TimeoutError(f"Endpoint '{endpoint_name}' did not become ready within {timeout_minutes} minutes")

        try:
            endpoint = client.serving_endpoints.get(name=endpoint_name)
            state = endpoint.state

            # Check if endpoint is ready
            if state and state.ready == EndpointStateReady.READY:
                # Verify the served model version
                served_entities = endpoint.config.served_entities if endpoint.config else []
                version_match = False
                served_version = None

                for entity in served_entities:
                    served_version = entity.entity_version
                    served_name = entity.entity_name
                    if served_name == expected_model_name and served_version == str(expected_version):
                        version_match = True
                        break

                if version_match:
                    print(f"✅ Endpoint is ready with correct version! (took {int(elapsed)}s)")
                    print(f"   Serving: {expected_model_name} v{expected_version}")
                    return endpoint
                else:
                    print(f"   Endpoint ready but serving v{served_version}, waiting for v{expected_version}... ({int(elapsed)}s elapsed)")
            else:
                config_update = state.config_update if state else None
                print(f"   Status: {state.ready if state else 'unknown'}, Config: {config_update} ({int(elapsed)}s elapsed)")

        except Exception as e:
            print(f"   Checking status... ({int(elapsed)}s elapsed): {e}")

        time.sleep(poll_interval_seconds)

# Wait for endpoint to be ready with the correct version
wait_for_endpoint_ready(w, endpoint_name, UC_MODEL_NAME, model_version)

print("\n🧪 Testing deployed endpoint...\n")

# Query using ResponsesAgent format - uses 'input' not 'messages'
# ResponsesAgent expects: input=[{role, content}, ...]
response = w.serving_endpoints.query(
    name=endpoint_name,
    input=[{"role": "user", "content": "What agents can you discover?"}]
)

print("✅ Response from deployed agent:")
print("-" * 40)
# ResponsesAgent returns 'output' not 'choices'
if hasattr(response, 'output') and response.output:
    # Output is a list of items, each with 'content' containing 'text'
    for item in response.output:
        if hasattr(item, 'content') and item.content:
            for content in item.content:
                if hasattr(content, 'text'):
                    print(content.text)
                    break
            break
elif isinstance(response, dict) and 'output' in response:
    for item in response['output']:
        if 'content' in item:
            for content in item['content']:
                if 'text' in content:
                    print(content['text'])
                    break
            break
else:
    print(response)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Query via SQL (ai_query)
# MAGIC
# MAGIC You can also query the deployed agent directly from SQL using `ai_query`:

# COMMAND ----------

# DBTITLE 1,Query Agent via SQL
result = spark.sql(f"""
  SELECT ai_query(
    '{endpoint_name}',
    'Hello! What agents do we have access to?'
  ) AS response
""")
display(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Register as A2A Agent (Optional)
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
# MAGIC This notebook deployed an **A2A-interoperable orchestrator agent** to Mosaic AI Framework using **OBO (On-Behalf-Of) authentication**:
# MAGIC
# MAGIC | Component | Description |
# MAGIC |-----------|-------------|
# MAGIC | **Agent** | LangGraph ReAct agent with A2A tools |
# MAGIC | **Tools** | `discover_agents`, `call_agent_via_gateway`, `call_a2a_agent` |
# MAGIC | **Auth** | OBO with apps, catalog, iam, and mcp scopes |
# MAGIC | **Registry** | Unity Catalog model: `{UC_MODEL_NAME}` |
# MAGIC | **Endpoint** | Model Serving with autoscaling |
# MAGIC
# MAGIC ### OBO Authentication Flow
# MAGIC
# MAGIC ```
# MAGIC User Request
# MAGIC     │
# MAGIC     ▼
# MAGIC Model Serving (OBO enabled)
# MAGIC     │ User identity extracted at runtime
# MAGIC     ▼
# MAGIC Agent predict() (OBO initialized here)
# MAGIC     │ WorkspaceClient with ModelServingUserCredentials
# MAGIC     ▼
# MAGIC A2A Gateway (Databricks App)
# MAGIC     │ User must have CAN_QUERY on app
# MAGIC     ▼
# MAGIC Gateway checks UC Connection access
# MAGIC     │ User must have USE_CONNECTION
# MAGIC     ▼
# MAGIC Downstream A2A Agents
# MAGIC ```
# MAGIC
# MAGIC ### Key Benefits
# MAGIC
# MAGIC 1. **Per-user access control** - OBO ensures the caller's identity is used throughout
# MAGIC 2. **UC-based authorization** - Gateway checks USE_CONNECTION privilege per agent
# MAGIC 3. **Runtime credential initialization** - OBO set up in `predict()` when user identity is known
# MAGIC 4. **Full traceability** - All calls are attributed to the original user

# COMMAND ----------

print("🎉 Deployment complete!")
print(f"\nEndpoint: {endpoint_name}")
print(f"Model: {UC_MODEL_NAME}")
