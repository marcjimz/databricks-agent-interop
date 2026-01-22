# A2A Gateway Notebooks

This folder contains interactive Databricks notebooks for demonstrating and using the A2A Gateway.

## Notebooks

### a2a_demo.py - A2A Protocol Demo

Demonstrates A2A protocol features using the official A2A SDK:
- Agent Discovery via `A2ACardResolver`
- Agent Card inspection
- Synchronous messaging via `ClientFactory`
- SSE Streaming
- Multi-agent orchestration
- A2A Client as LangChain tool pattern

### a2a_agent_deploy.py - Deploy to Mosaic AI Framework

Deploys an A2A orchestrator agent to Databricks Mosaic AI Framework:
- Build agent with LangChain/LangGraph + A2A SDK tools
- Log to MLflow (models-from-code pattern)
- Register to Unity Catalog
- Deploy with `agents.deploy()`
- Creates Model Serving endpoint with autoscaling, Review App, and inference tables

## Configuration

Copy `settings.yaml.example` to `settings.yaml` and configure:

```yaml
prefix: "your-prefix"
access_token: ""  # OAuth token from 'databricks auth token'
workspace_url_suffix: "-1444828305810485.aws.databricksapps.com"
catalog: "main"
schema: "default"
foundation_model: "databricks-meta-llama-3-1-8b-instruct"
```

### Getting an OAuth Token

Databricks Apps require OAuth authentication. Run this command locally:

```bash
databricks auth token --host "${DATABRICKS_HOST}"
```

Copy the token into `settings.yaml` or the notebook widget. Tokens expire after ~1 hour.

---

## Programmatic Access with Service Principals

For automated or programmatic access to Databricks Apps (including the A2A Gateway and agents), use a Service Principal instead of user tokens.

### 1. Create a Service Principal

```bash
# Create the service principal
databricks service-principals create \
  --display-name "a2a-gateway-sp" \
  --application-id <your-entra-app-id>
```

Or via the Databricks UI: **Settings → Identity and access → Service principals → Add**.

### 2. Generate OAuth Secret

```bash
# List service principals to get the ID
databricks service-principals list

# Create OAuth secret (note: secrets are shown only once)
databricks service-principals secrets create <service-principal-id>
```

Save the `client_id` (application ID) and `client_secret` from the response.

### 3. Grant App Access to the Service Principal

```bash
# Get the app's service principal ID
APP_SP_ID=$(databricks apps get "${PREFIX}-a2a-gateway" --output json | jq -r '.service_principal_id')

# Grant the SP permission to access the app
databricks permissions update serving-endpoints "${PREFIX}-a2a-gateway" \
  --json "{\"access_control_list\": [{\"service_principal_name\": \"a2a-gateway-sp\", \"permission_level\": \"CAN_QUERY\"}]}"
```

### 4. Use WorkspaceClient with Service Principal

```python
from databricks.sdk import WorkspaceClient
import httpx

# Initialize with SP credentials
w = WorkspaceClient(
    host="https://your-workspace.cloud.databricks.com",
    client_id="<your-client-id>",
    client_secret="<your-client-secret>"
)

# Get OAuth headers
auth_headers = w.config.authenticate()

# Call the A2A Gateway
gateway_url = "https://your-a2a-gateway.databricksapps.com"
with httpx.Client(headers=auth_headers) as client:
    response = client.get(f"{gateway_url}/api/agents")
    print(response.json())
```

### 5. Grant UC Connection Access to SP

For the SP to access specific agents, grant `USE_CONNECTION` privilege:

```bash
databricks grants update connection "${PREFIX}-echo-a2a" \
  --json '{"changes": [{"add": ["USE_CONNECTION"], "principal": "a2a-gateway-sp"}]}'
```

This enables fully automated agent-to-agent communication without user intervention.
