# Databricks A2A Gateway

A2A protocol gateway for Databricks. Discovers agents via UC connections (`*-a2a`), authorizes via connection access.

## Architecture

**Gateway** (`app/`) - FastAPI application that:
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

- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) configured with your default profile
- `make`

## Deploy

```bash
make auth
make deploy PREFIX=<your-prefix>
make status
```

## Register Agents

We deployed two example agents as part of this orchestration, governance setup is as follows:

**Convention**:
- Connection name ends with `-a2a` → agent is discoverable by the gateway
- Connection URL → **agent card URL** (the JSON endpoint, e.g., `/.well-known/agent.json`)

```bash
# Get agent URLs and construct agent card URLs
ECHO_CARD=$(databricks apps get ${PREFIX}-echo-agent --output json | jq -r '.url + "/.well-known/agent.json"')
CALC_CARD=$(databricks apps get ${PREFIX}-calculator-agent --output json | jq -r '.url + "/.well-known/agent.json"')

# Create UC connections - URL points to agent card JSON
databricks connections create --name "echo-a2a" --connection-type HTTP \
  --options "{\"url\": \"${ECHO_CARD}\"}" --comment "Echo Agent"

databricks connections create --name "calculator-a2a" --connection-type HTTP \
  --options "{\"url\": \"${CALC_CARD}\"}" --comment "Calculator Agent"

# Grant access
databricks grants update connection echo-a2a \
  --json '{"changes": [{"add": ["USE_CONNECTION"], "principal": "data-scientists"}]}'
```

For non-standard agent card paths (e.g., ServiceNow):
```bash
# ServiceNow uses custom path
databricks connections create --name "servicenow-a2a" --connection-type HTTP \
  --options '{"url": "https://myinstance.service-now.com/api/sn_aia/a2a/id/ABC123/well_known/agent_json"}'
```

## Usage

### 1. Explore the API

Open Swagger UI at `https://<gateway-url>/docs` to interactively test all endpoints.

### 2. Discover Accessible Agents

```bash
curl -s https://<gateway-url>/api/agents | jq
```

Response (only agents you have UC connection access to):
```json
{
  "agents": [
    {
      "name": "echo",
      "description": "Echo Agent - Returns messages for A2A testing",
      "url": "https://marcin-echo-agent-xxx.databricksapps.com",
      "connection_name": "echo-a2a"
    }
  ],
  "total": 1
}
```

### 3. Call an Agent

```bash
curl -X POST https://<gateway-url>/api/agents/echo/message \
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
curl -s https://<gateway-url>/api/agents/calculator/message \
  -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{...}}'
```

Response:
```json
{
  "detail": "Access denied to agent connection: calculator-a2a. Ensure you have USE_CONNECTION privilege."
}
```

### 5. Grant/Revoke Access

Grant access:
```sql
GRANT USE CONNECTION ON CONNECTION `calculator-a2a` TO `user@example.com`;
```

Now the same request succeeds. Revoke to deny:
```sql
REVOKE USE CONNECTION ON CONNECTION `calculator-a2a` FROM `user@example.com`;
```

### 6. Agent-to-Agent via Gateway

An agent can call other agents through the gateway. Configure your agent to use the gateway URL:

```python
# In your agent code
import httpx

async def call_calculator(expression: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://<gateway-url>/api/agents/calculator/message",
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
- Connection URL = agent card JSON URL (e.g., `https://agent.com/.well-known/agent.json`)
- Gateway fetches the agent card and uses the `url` field for messaging

**Authorization**: Uses Databricks OBO (On-Behalf-Of) to check if the calling user/principal can access the UC connection.

**Interoperability**: Any A2A-compliant agent can be registered (ServiceNow, Workday, custom). The gateway fetches the agent card and proxies to the endpoint URL specified in the card.

## Commands

| Command | Description |
|---------|-------------|
| `make deploy` | Deploy bundle + start apps |
| `make redeploy` | Redeploy apps (code changes) |
| `make status` | Check app status and URLs |
| `make stop` | Stop all apps |
| `make destroy` | Remove all resources |
