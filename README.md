# Databricks A2A Gateway

An [A2A protocol](https://google.github.io/A2A/) gateway powered by an **Agent Registry** built on Databricks Unity Catalog. The gateway leverages native UC objects (HTTP connections) for agent discovery and access control, enabling seamless interoperability between A2A-compliant agents.

For more on AI Agent Protocols, reference the helpful paper: [A Survey of AI Agent Protocols](https://arxiv.org/pdf/2504.16736)

![AgentProtocols](./static/img/agent_protocols.png)

## Architecture

**Gateway** (`gateway/`) - FastAPI application that:
- Discovers agents via UC connections ending with `-a2a`
- Authorizes using OBO (On-Behalf-Of) to check user's connection access
- Proxies requests to downstream agents with SSE streaming support

**Endpoints:**
| Endpoint | Purpose |
|----------|---------|
| `GET /` | Gateway info |
| `GET /docs` | Swagger UI |
| `GET /api/agents` | List accessible agents |
| `GET /api/agents/{name}` | Get agent info |
| `POST /api/agents/{name}/message` | Send JSON-RPC message |
| `GET /.well-known/agent.json` | Gateway's A2A agent card |

**Demo Agents** (`src/agents/`)
- Echo Agent - Simple echo back for testing
- Calculator Agent - Arithmetic with LangChain tools

## Prerequisites

- **Azure Databricks** with Microsoft Entra ID authentication
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) configured with your default profile
- `make`

## Deploy

```bash
PREFIX=marcin
make auth
make deploy PREFIX=$PREFIX
make status
```

## Register Agents

We deployed two example agents as part of this orchestration, governance setup is as follows:

**Convention**:
- Connection name ends with `-a2a` → agent is discoverable by the gateway
- `host` = agent base URL (no path)
- `base_path` = agent card path (e.g., `/.well-known/agent.json`)

```bash
# Set your prefix (same as used in make deploy); this is not required for anything other than to avoid duplicates in a workspace. Repeated for consistency.
# PREFIX=<your-prefix>

# Get agent base URLs
ECHO_URL=$(databricks apps get "${PREFIX}-echo-agent" --output json | jq -r '.url')
CALC_URL=$(databricks apps get "${PREFIX}-calculator-agent" --output json | jq -r '.url')

# Create UC connections - "databricks" indicates same-tenant Entra ID pass-through
databricks connections create --json "{
  \"name\": \"${PREFIX}-echo-a2a\",
  \"connection_type\": \"HTTP\",
  \"options\": {\"host\": \"${ECHO_URL}\", \"base_path\": \"/.well-known/agent.json\", \"bearer_token\": \"databricks\"},
  \"comment\": \"Echo Agent\"
}"

databricks connections create --json "{
  \"name\": \"${PREFIX}-calculator-a2a\",
  \"connection_type\": \"HTTP\",
  \"options\": {\"host\": \"${CALC_URL}\", \"base_path\": \"/.well-known/agent.json\", \"bearer_token\": \"databricks\"},
  \"comment\": \"Calculator Agent\"
}"

# Grant access
databricks grants update connection "${PREFIX}-echo-a2a" \
  --json '{"changes": [{"add": ["USE_CONNECTION"], "principal": "data-scientists"}]}'
```

### External Agents (Different Tenant / No Entra ID)

For agents outside your Azure tenant, UC HTTP connections support multiple auth methods:

**Option 1: Static Bearer Token**
```bash
databricks connections create --json '{
  "name": "servicenow-a2a",
  "connection_type": "HTTP",
  "options": {
    "host": "https://myinstance.service-now.com",
    "base_path": "/api/sn_aia/a2a/id/ABC123/well_known/agent_json",
    "bearer_token": "your-static-token"
  }
}'
```

**Option 2: OAuth M2M (Client Credentials Flow)** - Recommended for A2A
```bash
databricks connections create --json '{
  "name": "workday-a2a",
  "connection_type": "HTTP",
  "options": {
    "host": "https://mycompany.workday.com",
    "base_path": "/.well-known/agent.json",
    "client_id": "your-client-id",
    "client_secret": "your-client-secret",
    "token_endpoint": "https://auth.workday.com/oauth2/token",
    "oauth_scope": "a2a.agents"
  }
}'
```

The gateway automatically acquires and caches OAuth tokens when using M2M credentials.

## Usage

First, capture the gateway URL and auth token:

```bash
# Set your prefix and Databricks host
PREFIX=marcin
DATABRICKS_HOST=https://e2-demo-field-eng.cloud.databricks.com/

# Get gateway URL and auth token
GATEWAY_URL=$(databricks apps get "${PREFIX}-a2a-gateway" --output json | jq -r '.url')
TOKEN=$(databricks auth token --host "${DATABRICKS_HOST}" | jq -r '.access_token')
```

> **Note**: If `databricks auth token` prompts for host, ensure you've logged in first:
> ```bash
> databricks auth login --host "${DATABRICKS_HOST}"
> ```

### 1. Explore the API

Open Swagger UI at `${GATEWAY_URL}/docs` to interactively test all endpoints.

### 2. Discover Accessible Agents

```bash
curl -s "${GATEWAY_URL}/api/agents" \
  -H "Authorization: Bearer ${TOKEN}" | jq
```

Response (only agents you have UC connection access to):
```json
{
  "agents": [
    {
      "name": "marcin-calculator",
      "description": "Calculator Agent",
      "agent_card_url": "https://marcin-calculator-agent-1444828305810485.aws.databricksapps.com/.well-known/agent.json",
      "url": null,
      "bearer_token": null,
      "oauth_m2m": null,
      "connection_name": "marcin-calculator-a2a",
      "catalog": "main",
      "schema_name": "default"
    },
    {
      "name": "marcin-echo",
      "description": "Echo Agent",
      "agent_card_url": "https://marcin-echo-agent-1444828305810485.aws.databricksapps.com/.well-known/agent.json",
      "url": null,
      "bearer_token": null,
      "oauth_m2m": null,
      "connection_name": "marcin-echo-a2a",
      "catalog": "main",
      "schema_name": "default"
    }
  ],
  "total": 2
}
```

### 3. Call an Agent

```bash
curl -X POST "${GATEWAY_URL}/api/agents/marcin-echo/message" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "messageId": "msg-1",
        "role": "user",
        "parts": [{"kind": "text", "text": "Hello from A2A!"}]
      }
    }
  }' | jq
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "artifacts": [{"parts": [{"kind": "text", "text": "Echo: Hello from A2A!"}]}],
    "status": "completed"
  }
}
```

### 4. Access Denied (No UC Connection Access)

If you don't have `USE CONNECTION` privilege:

```bash
curl -s "${GATEWAY_URL}/api/agents/${PREFIX}-calculator/message" \
  -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"messageId":"msg-1","role":"user","parts":[{"kind":"text","text":"Hello"}]}}}' | jq
```

Response:
```json
{
  "error": "Access denied to agent connection: <prefix>-calculator-a2a. Ensure you have USE_CONNECTION privilege."
}
```

### 5. Grant/Revoke Access

Grant access:
```bash
databricks grants update connection "${PREFIX}-calculator-a2a" \
    --json '{"changes": [{"add": ["USE_CONNECTION"], "principal": "marcin.jimenez@databricks.com"}]}'
```

Now the same request succeeds. Revoke to deny:
```bash
databricks grants update connection "${PREFIX}-calculator-a2a" \
    --json '{"changes": [{"remove": ["USE_CONNECTION"], "principal": "marcin.jimenez@databricks.com"}]}'
```

### 6. Agent-to-Agent via Gateway

An agent can call other agents through the gateway. Configure your agent to use the gateway URL:

```python
# In your agent code
import os
import httpx

GATEWAY_URL = os.environ.get("GATEWAY_URL", "https://your-gateway.databricksapps.com")

async def call_calculator(expression: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GATEWAY_URL}/api/agents/calculator/message",
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "agent-call-1",
                        "role": "user",
                        "parts": [{"kind": "text", "text": expression}]
                    }
                }
            }
        )
        return response.json()

# Agent can now use calculator if it has UC connection access
result = await call_calculator("Add 42 and 17")
```

The gateway enforces the same UC connection access for agent-to-agent calls - the calling agent's service principal must have `USE CONNECTION` privilege.

## Key Concepts

**Discovery Standard**:
- UC HTTP connection name ends with `-a2a` → agent is discoverable
- Connection options:
  - `host` = agent base URL (e.g., `https://agent.com`)
  - `base_path` = agent card path (e.g., `/.well-known/agent.json`)
- Gateway fetches the agent card from `host` + `base_path` and uses the `url` field for messaging

**Authorization**: Uses Databricks OBO (On-Behalf-Of) to check if the calling user/principal can access the UC connection.

**Authentication to Downstream Agents** (aligned with [A2A OAuth support](https://google.github.io/A2A/)):
| Scenario | Connection Options | Auth Method |
|----------|-------------------|-------------|
| Same Azure tenant | `bearer_token: "databricks"` | Gateway passes caller's Entra ID token |
| External (static token) | `bearer_token: "<token>"` | Gateway uses stored token |
| External (OAuth M2M) | `client_id`, `client_secret`, `token_endpoint` | Gateway acquires token via client credentials flow |

**Interoperability**: Any A2A-compliant agent can be registered (ServiceNow, Workday, custom). The gateway fetches the agent card and proxies to the endpoint URL specified in the card.

## Commands

| Command | Description |
|---------|-------------|
| `make deploy` | Deploy bundle + restart apps |
| `make status` | Check app status and URLs |
| `make stop` | Stop all apps |
| `make start` | Start all apps |
| `make destroy` | Remove all resources |
