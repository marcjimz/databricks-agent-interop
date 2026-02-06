# Databricks A2A Gateway Framework

![./static/img/dbx-banner.jpeg](./static/img/dbx-banner.jpeg)

A framework for [A2A Protocol](https://a2a-protocol.org/) interoperability on Databricks, powered by **Azure API Management** and **Unity Catalog** for agent discovery and access control.

For more on AI Agent Protocols, see: [A Survey of AI Agent Protocols](https://arxiv.org/pdf/2504.16736)

![AgentProtocols](./static/img/agent_protocols.png)

## What's Included

| Component | Description |
|-----------|-------------|
| **APIM Gateway** | Azure API Management policies for auth, discovery, and proxying |
| **Terraform** | Infrastructure-as-code for deploying APIM + App Insights |
| **Scripts** | CLI tools for creating UC connections and generating agent cards |
| **Integration Guides** | Docs for Foundry and Copilot Studio |

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Client         │────▶│  Azure APIM     │────▶│  Backend Agents │
│  (Foundry,      │     │  (Gateway)      │     │  (Your services,│
│   Copilot)      │     │                 │     │   External A2A) │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                        ┌────────▼────────┐
                        │  Unity Catalog  │
                        │  (Connections)  │
                        └─────────────────┘
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Discovery** | UC HTTP connection name ends with `-a2a` → agent is discoverable |
| **Authorization** | `USE_CONNECTION` privilege controls who can access each agent |
| **Auth Flow** | Entra ID token → APIM validates → exchanges for Databricks token → UC check |
| **Agent Cards** | Generated dynamically from UC connection metadata (A2A spec compliant) |

## Prerequisites

- Azure CLI logged in (`az login`)
- Databricks CLI configured (`databricks auth login`)
- Terraform installed
- Databricks workspace federated with your Entra ID tenant

## Quick Start

### 1. Deploy

```bash
cd infra/

terraform init

terraform apply \
  -var="entra_tenant_id=YOUR_ENTRA_TENANT_ID" \
  -var="databricks_host=https://your-workspace.azuredatabricks.net" \
  -var="databricks_workspace_id=YOUR_WORKSPACE_ID" \
  -var="apim_publisher_email=you@company.com"

# Get the gateway URL
export GATEWAY_URL=$(terraform output -raw a2a_gateway_base_url)
echo $GATEWAY_URL
```

### 2. Register an Agent

```bash
# Create UC connection pointing to your backend agent
python scripts/create_agent_connection.py \
  --name myagent \
  --host https://your-backend-agent.azurewebsites.net \
  --base-path /a2a

# Grant yourself access
databricks grants update connection myagent-a2a \
  --json '{"changes":[{"add":["USE_CONNECTION"],"principal":"you@company.com"}]}'
```

### 3. Get a Token

```bash
export TOKEN=$(az account get-access-token \
  --resource https://management.azure.com \
  --query accessToken -o tsv)
```

### 4. Test

```bash
# List agents you have access to
curl -s -H "Authorization: Bearer $TOKEN" "$GATEWAY_URL/agents" | jq

# Get agent card
curl -s -H "Authorization: Bearer $TOKEN" \
  "$GATEWAY_URL/agents/myagent/.well-known/agent.json" | jq

# Send a message
curl -s -X POST "$GATEWAY_URL/agents/myagent" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "Hello!"}]
      }
    }
  }' | jq
```

## Gateway Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agents` | GET | List accessible agents |
| `/agents/{name}` | GET | Get agent info |
| `/agents/{name}/.well-known/agent.json` | GET | Get A2A agent card |
| `/agents/{name}` | POST | A2A JSON-RPC proxy |
| `/agents/{name}/stream` | POST | A2A streaming (SSE) |

## Grant/Revoke Access

```bash
# Grant access
databricks grants update connection myagent-a2a \
  --json '{"changes":[{"add":["USE_CONNECTION"],"principal":"user@company.com"}]}'

# Revoke access
databricks grants update connection myagent-a2a \
  --json '{"changes":[{"remove":["USE_CONNECTION"],"principal":"user@company.com"}]}'
```

## Testing

```bash
# Install test dependencies
pip install -r tests/requirements.txt

# Run unit tests
pytest tests/unit/

# Run integration tests
APIM_GATEWAY_URL=$GATEWAY_URL DATABRICKS_TOKEN=$TOKEN pytest tests/integration/

# Test agent card compliance
python scripts/test_agent_card_compliance.py --mock
```

## Integration Guides

| Platform | Guide |
|----------|-------|
| Azure AI Foundry | [docs/integration/FOUNDRY.md](docs/integration/FOUNDRY.md) |
| Microsoft Copilot Studio | [docs/integration/COPILOT.md](docs/integration/COPILOT.md) |
