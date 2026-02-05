# Azure AI Foundry A2A Infrastructure

This folder contains Terraform configuration and scripts to deploy Azure AI Foundry with A2A (Agent-to-Agent) protocol support, enabling bidirectional communication between Azure AI agents and Databricks agents via the A2A Gateway.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Same Entra ID Tenant                                   │
│                                                                                  │
│  ┌───────────────────────────────┐         ┌───────────────────────────────┐    │
│  │     Azure AI Foundry          │         │     Databricks                │    │
│  │                               │         │                               │    │
│  │  ┌─────────────────────────┐  │         │  ┌─────────────────────────┐  │    │
│  │  │  AI Foundry Hub         │  │         │  │  A2A Gateway            │  │    │
│  │  │  └── Project            │  │         │  │  (Databricks App)       │  │    │
│  │  │      └── Agent          │  │◀───────▶│  │                         │  │    │
│  │  │          (A2A Tool)     │  │  A2A    │  │  Unity Catalog          │  │    │
│  │  └─────────────────────────┘  │         │  │  Access Control         │  │    │
│  │                               │         │  └─────────────────────────┘  │    │
│  │  ┌─────────────────────────┐  │         │              │                │    │
│  │  │  AI Services            │  │         │              ▼                │    │
│  │  │  (GPT-4, etc.)          │  │         │  ┌─────────────────────────┐  │    │
│  │  └─────────────────────────┘  │         │  │  Databricks Agents      │  │    │
│  │                               │         │  │  (Echo, Calculator)     │  │    │
│  └───────────────────────────────┘         │  └─────────────────────────┘  │    │
│                                            │                               │    │
│                                            │  ┌─────────────────────────┐  │    │
│                                            │  │  UC HTTP Connection     │  │    │
│                                            │  │  (Azure Agent → A2A)    │  │    │
│                                            │  └─────────────────────────┘  │    │
│                                            └───────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Azure subscription (same Entra ID tenant as Databricks workspace)
- Terraform >= 1.0
- Azure CLI installed and authenticated (`az login`)
- Databricks CLI installed and authenticated
- Databricks A2A Gateway deployed (`make deploy-gateway`)

## Quick Start

### 1. Deploy Azure Infrastructure

```bash
# From repository root
make deploy-azure PREFIX=yourprefix
```

Or manually:

```bash
cd infra/azure/terraform

# Initialize Terraform
terraform init

# Set variables
export TF_VAR_prefix="yourprefix"
export TF_VAR_location="eastus"
export TF_VAR_databricks_gateway_url="https://yourprefix-a2a-gateway.databricksapps.com"
export TF_VAR_tenant_id="$(az account show --query tenantId -o tsv)"

# Deploy
terraform apply
```

### 2. Verify Deployment

```bash
# Check Azure resources
make status-azure

# Or manually
cd infra/azure/terraform
terraform output
```

### 3. Test A2A Connection

```bash
make test-azure
```

## Folder Structure

```
infra/azure/
├── README.md                    # This file
├── terraform/
│   ├── providers.tf             # Azure provider configuration
│   ├── variables.tf             # Input variables
│   ├── main.tf                  # AI Foundry hub, project, dependencies
│   ├── a2a-connection.tf        # A2A connection to Databricks gateway
│   ├── outputs.tf               # Deployment outputs
│   └── terraform.tfvars.example # Example variable values
└── scripts/
    ├── deploy.sh                # Deployment script
    ├── test-agent.sh            # Test A2A agent
    └── create-uc-connection.sh  # Register Azure agent in Databricks UC
```

## Configuration

### Terraform Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `prefix` | Resource name prefix (should match Databricks PREFIX) | - |
| `location` | Azure region | `eastus` |
| `databricks_gateway_url` | URL of Databricks A2A Gateway | - |
| `tenant_id` | Entra ID tenant ID | - |
| `model_deployment_name` | Model to deploy (e.g., gpt-4o) | `gpt-4o` |

### Example terraform.tfvars

```hcl
prefix                   = "marcin"
location                 = "eastus"
databricks_gateway_url   = "https://marcin-a2a-gateway.databricksapps.com"
tenant_id                = "your-tenant-id"
model_deployment_name    = "gpt-4o"
```

## What Gets Deployed

| Resource | Purpose |
|----------|---------|
| Resource Group | Container for all Azure resources |
| Key Vault | Secrets management |
| Storage Account | AI Foundry storage |
| AI Services | Model hosting (GPT-4, etc.) |
| AI Foundry Hub | Central AI workspace |
| AI Foundry Project | Project within hub |
| A2A Connection | Connection to Databricks A2A Gateway |

---

## Registering Azure Agents in Unity Catalog

To make Azure AI Foundry agents discoverable through the Databricks A2A Gateway, register them as UC HTTP connections following our A2A standard.

### A2A Discovery Standard

Our gateway uses the following convention for agent discovery:

1. **Connection name** must end with `-a2a` (e.g., `azure-foundry-a2a`)
2. **Connection options**:
   - `host`: Agent base URL
   - `base_path`: Path to agent card (typically `/.well-known/agent.json`)
   - Authentication: `bearer_token: "databricks"` for same-tenant, or OAuth M2M for cross-tenant

### Option 1: Azure AI Foundry Agent (Native A2A)

Azure AI Foundry exposes agents via the Foundry Agent Service API. To register a Foundry agent in UC:

```bash
# Get your Foundry project endpoint
FOUNDRY_PROJECT_ENDPOINT=$(cd infra/azure/terraform && terraform output -raw ai_foundry_project_endpoint)
AGENT_NAME="your-agent-name"

# The A2A endpoint format for Foundry agents
# Note: Foundry agents use the project endpoint with agent-specific paths
AGENT_A2A_URL="${FOUNDRY_PROJECT_ENDPOINT}/agents/${AGENT_NAME}"

# Create UC connection (same tenant - Entra ID pass-through)
databricks connections create --json "{
  \"name\": \"azure-foundry-${AGENT_NAME}-a2a\",
  \"connection_type\": \"HTTP\",
  \"options\": {
    \"host\": \"${AGENT_A2A_URL}\",
    \"base_path\": \"/.well-known/agent.json\",
    \"bearer_token\": \"databricks\"
  },
  \"comment\": \"Azure AI Foundry agent: ${AGENT_NAME}\"
}"
```

### Option 2: Custom A2A Agent (Hosted on Azure)

If you deploy a custom A2A-compliant agent on Azure (Container Apps, App Service, etc.):

```bash
# Your custom agent URL
CUSTOM_AGENT_URL="https://your-agent.azurecontainerapps.io"

# Create UC connection
databricks connections create --json "{
  \"name\": \"azure-custom-agent-a2a\",
  \"connection_type\": \"HTTP\",
  \"options\": {
    \"host\": \"${CUSTOM_AGENT_URL}\",
    \"base_path\": \"/.well-known/agent.json\",
    \"bearer_token\": \"databricks\"
  },
  \"comment\": \"Custom A2A agent hosted on Azure\"
}"
```

### Option 3: Cross-Tenant Agent (OAuth M2M)

For agents in a different Entra ID tenant, use OAuth client credentials:

```bash
databricks connections create --json '{
  "name": "external-azure-agent-a2a",
  "connection_type": "HTTP",
  "options": {
    "host": "https://external-agent.example.com",
    "base_path": "/.well-known/agent.json",
    "client_id": "your-client-id",
    "client_secret": "your-client-secret",
    "token_endpoint": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
    "oauth_scope": "api://agent-app-id/.default"
  },
  "comment": "External Azure agent (cross-tenant)"
}'
```

### Grant Access to Azure Agents

After creating the UC connection, grant access to users/groups:

```bash
# Grant to a user
databricks grants update connection "azure-foundry-myagent-a2a" \
  --json '{"changes": [{"add": ["USE_CONNECTION"], "principal": "user@company.com"}]}'

# Grant to a group
databricks grants update connection "azure-foundry-myagent-a2a" \
  --json '{"changes": [{"add": ["USE_CONNECTION"], "principal": "data-scientists"}]}'

# Grant to gateway service principal (for service-to-service)
GATEWAY_SP=$(databricks apps get ${PREFIX}-a2a-gateway --output json | jq -r '.service_principal_client_id')
databricks grants update connection "azure-foundry-myagent-a2a" \
  --json "{\"changes\": [{\"add\": [\"USE_CONNECTION\"], \"principal\": \"${GATEWAY_SP}\"}]}"
```

### Verify Agent Discovery

```bash
# Get gateway URL and token
GATEWAY_URL=$(databricks apps get ${PREFIX}-a2a-gateway --output json | jq -r '.url')
TOKEN=$(databricks auth token | jq -r '.access_token')

# List all discoverable agents (should include Azure agents)
curl -s "${GATEWAY_URL}/api/agents" \
  -H "Authorization: Bearer ${TOKEN}" | jq

# Get specific Azure agent info
curl -s "${GATEWAY_URL}/api/agents/azure-foundry-myagent" \
  -H "Authorization: Bearer ${TOKEN}" | jq
```

---

## A2A Agent Card Specification

For custom agents to be discoverable, they must expose an agent card at `/.well-known/agent.json`:

```json
{
  "name": "azure-demo-agent",
  "description": "Demo A2A agent hosted on Azure",
  "url": "/a2a",
  "version": "1.0.0",
  "protocol": "a2a",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "analyze",
      "name": "Analyze Data",
      "description": "Analyzes provided data and returns insights"
    }
  ],
  "authentication": {
    "schemes": ["bearer"]
  }
}
```

### Required Fields

| Field | Description |
|-------|-------------|
| `name` | Unique agent identifier |
| `description` | Human-readable description |
| `url` | Endpoint for A2A JSON-RPC requests (relative or absolute) |
| `version` | Agent version |

### Optional Fields

| Field | Description |
|-------|-------------|
| `protocol` | Should be `"a2a"` |
| `capabilities` | Streaming, push notifications support |
| `skills` | List of agent capabilities/tools |
| `authentication` | Supported auth schemes |

---

## Creating an A2A-Compliant Azure Agent

Here's a minimal A2A agent implementation for Azure:

### Python (FastAPI)

```python
"""A2A-compliant agent for Azure deployment."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

AGENT_CARD = {
    "name": "azure-demo-agent",
    "description": "Demo A2A agent hosted on Azure",
    "url": "/a2a",
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "skills": [
        {"id": "echo", "name": "Echo", "description": "Echoes input"}
    ]
}

@app.get("/.well-known/agent.json")
async def agent_card():
    """Return A2A agent card for discovery."""
    return AGENT_CARD

@app.post("/a2a")
async def handle_a2a(request: Request):
    """Handle A2A JSON-RPC requests."""
    body = await request.json()

    # Validate JSON-RPC
    if body.get("jsonrpc") != "2.0":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "error": {"code": -32600, "message": "Invalid Request"}
        }, status_code=400)

    method = body.get("method", "")
    params = body.get("params", {})
    request_id = body.get("id", "1")

    # Handle message/send
    if method == "message/send":
        message = params.get("message", {})
        parts = message.get("parts", [])

        # Extract text
        input_text = ""
        for part in parts:
            if part.get("kind") == "text":
                input_text = part.get("text", "")
                break

        # Process and respond
        response_text = f"Azure says: {input_text}"

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "status": "completed",
                "artifacts": [{
                    "parts": [{"kind": "text", "text": response_text}]
                }]
            }
        })

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }, status_code=400)

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Deploy to Azure Container Apps

```bash
# Create resource group
az group create --name a2a-agents-rg --location eastus

# Create Container App Environment
az containerapp env create \
  --name a2a-env \
  --resource-group a2a-agents-rg \
  --location eastus

# Deploy agent
az containerapp create \
  --name azure-demo-agent \
  --resource-group a2a-agents-rg \
  --environment a2a-env \
  --image your-registry.azurecr.io/azure-demo-agent:latest \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1

# Get URL
AGENT_URL=$(az containerapp show \
  --name azure-demo-agent \
  --resource-group a2a-agents-rg \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "Agent URL: https://${AGENT_URL}"
```

### Register in Databricks UC

```bash
# After deploying the agent
./scripts/create-uc-connection.sh azure-demo-agent "https://${AGENT_URL}"
```

---

## Bidirectional A2A Flow

### Azure → Databricks (via A2A Tool)

Azure AI Foundry agents can call Databricks agents using the A2A Tool:

```python
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, A2ATool

# Create agent with A2A tool pointing to Databricks gateway
tool = A2ATool(project_connection_id=databricks_gateway_connection_id)

agent = client.agents.create_version(
    agent_name="orchestrator",
    definition=PromptAgentDefinition(
        model="gpt-4o",
        instructions="Use Databricks agents for calculations and data tasks.",
        tools=[tool],
    ),
)
```

### Databricks → Azure (via UC Connection)

Databricks agents can call Azure agents via the A2A Gateway:

```python
from a2a import A2AClient

# Client automatically uses gateway with UC auth
client = A2AClient(
    gateway_url="https://prefix-a2a-gateway.databricksapps.com",
    agent_name="azure-demo-agent"
)

response = await client.send_message("Analyze this data")
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Agent not discovered | Connection name doesn't end with `-a2a` | Rename connection with `-a2a` suffix |
| 401 Unauthorized | Token not passed correctly | Verify `bearer_token: "databricks"` for same-tenant |
| 403 Forbidden | Missing UC permissions | Grant `USE_CONNECTION` to user/principal |
| Agent card fetch fails | Wrong `base_path` | Verify agent exposes `/.well-known/agent.json` |
| A2A call timeout | Network/firewall issues | Check agent is publicly accessible or VNet peering |

### Debug Commands

```bash
# Test agent card directly
curl -v "https://your-agent-url/.well-known/agent.json"

# Test A2A endpoint directly
curl -X POST "https://your-agent-url/a2a" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "messageId": "test-1",
        "role": "user",
        "parts": [{"kind": "text", "text": "Hello"}]
      }
    }
  }'

# Check UC connection
databricks connections get "azure-demo-a2a"

# Check grants
databricks grants get connection "azure-demo-a2a"
```

---

## References

- [A2A Protocol Specification](https://google.github.io/A2A/)
- [Azure AI Foundry A2A Documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/agent-to-agent)
- [A2A Authentication](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/agent-to-agent-authentication)
- [Databricks A2A Gateway](../README.md)
