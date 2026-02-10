# Databricks Agent Interoperability Framework

![./static/img/dbx-banner.jpeg](./static/img/dbx-banner.jpeg)

A framework for **agent interoperability** on Databricks, where **Unity Catalog** is the heart for discovery, governance, and traceability. Wrap any agent—internal or external—as a UC Function and expose it via **MCP (Model Context Protocol)** for seamless access across platforms.

## Prerequisites

| Tool | Installation |
|------|--------------|
| Terraform | https://terraform.io/downloads |
| Azure CLI | https://aka.ms/installazurecli |
| Databricks CLI | `pip install databricks-cli` |
| Python 3.10+ | https://python.org |

```bash
# Verify installations
terraform --version
az --version
databricks --version
```

---

## Three Pillars

| Pillar | What It Means |
|--------|---------------|
| **Interoperability** | External agents wrapped as UC Functions, exposed via MCP |
| **Governance** | Unity Catalog provides discovery, access control, and audit trails |
| **Performance** | Multi-agent orchestration via [Agent Bricks](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/) |

## Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                        Unity Catalog                              │
│                  (Discovery + Governance + Audit)                 │
│                                                                   │
│   UC Functions          UC Connections          UC Permissions    │
│   (MCP Tools)           (Credentials)           (EXECUTE grants)  │
└───────────────────────────────┬───────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                    Databricks Managed MCP                         │
│            /api/2.0/mcp/functions/{catalog}/{schema}              │
└───────────────────────────────┬───────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
   Databricks              Azure AI                 Any MCP
    Agents                 Foundry                  Client


┌─────────────────── UC Functions as Wrappers ───────────────────────┐
│                                                                     │
│   ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐│
│   │   echo_agent    │    │calculator_agent │    │epic_patient_    ││
│   │   (UC Func)     │    │   (UC Func)     │    │search (UC Func) ││
│   └────────┬────────┘    └────────┬────────┘    └────────┬────────┘│
│            │                      │                      │          │
│            ▼                      ▼                      ▼          │
│   ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐│
│   │  Echo Agent     │    │Calculator Agent │    │  Epic FHIR      ││
│   │ (Databricks App)│    │(Databricks App) │    │  (Stub API)     ││
│   │ ResponsesAgent  │    │ ResponsesAgent  │    │                 ││
│   └─────────────────┘    └─────────────────┘    └─────────────────┘│
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Step 0: Configure Environment

Create your configuration file before deploying infrastructure.

```bash
# Create .env from template
make setup

# Edit .env with your Azure values
```

### .env Configuration

```bash
# Required for infrastructure deployment
TENANT_ID=your-azure-tenant-id
SUBSCRIPTION_ID=your-azure-subscription-id
LOCATION=eastus2
PREFIX=mcp-interop

# Unity Catalog
UC_CATALOG=mcp_agents
UC_SCHEMA=tools

# Set automatically after deployment (Step 1)
# DATABRICKS_HOST=https://adb-xxxx.azuredatabricks.net
# FOUNDRY_ENDPOINT=https://your-foundry.azure.com
```

After infrastructure deployment, `DATABRICKS_HOST` and `FOUNDRY_ENDPOINT` are automatically added to your `.env` file.

---

## Step 1: Deploy Infrastructure

Infrastructure deployment is split into two phases to handle cross-tenant metastore scenarios.

### Phase 1: Deploy Azure Resources

```bash
make deploy-infra
```

This deploys:

| Resource | Purpose |
|----------|---------|
| Azure Databricks Workspace | Premium SKU for Unity Catalog |
| Azure AI Foundry | AI Hub + AI Services + Project |
| Storage Accounts | For Unity Catalog and AI Foundry |
| Access Connector | Managed identity for UC storage access |

After deployment, your `.env` is updated with:
- `DATABRICKS_HOST` — Your workspace URL
- `FOUNDRY_ENDPOINT` — Your AI Foundry endpoint

### Phase 2: Assign Metastore (Manual)

1. Go to [Databricks Account Console](https://accounts.azuredatabricks.net)
2. Navigate to **Data** → **Metastores**
3. Select your metastore and click **Assign to workspace**
4. Choose the newly created workspace (`dbx-mcp-interop`)

### Phase 3: Deploy Unity Catalog Resources

After metastore assignment:

```bash
make deploy-uc
```

This creates:

| Resource | Purpose |
|----------|---------|
| Storage Credential | Links Access Connector to UC |
| External Location | Points to ADLS storage |
| Catalog `mcp_agents` | Container for MCP tools |
| Schema `mcp_agents.tools` | Where UC Functions live |

The `make deploy-uc` command also deploys a notebook to your workspace via Databricks Asset Bundles. After running it, you'll see a URL to open the notebook.

---

## Step 2: Register UC Functions as MCP Tools

Open the notebook URL provided by `make deploy-uc` and run all cells. This registers the UC Functions which automatically become MCP tools.

The notebook registers:

| Function | Description |
|----------|-------------|
| `echo_agent` | Calls the Echo Agent (Databricks App) via MLflow `/invocations` endpoint |
| `calculator_agent` | Calls the Calculator Agent (Databricks App) via MLflow `/invocations` endpoint |
| `epic_patient_search` | FHIR Patient search stub (simulates Epic Sandbox API) |

### Verify Registration

```sql
SHOW FUNCTIONS IN mcp_agents.tools;
```

---

## Step 3: Test from Databricks

### 3a. SQL

```sql
-- Test echo agent (requires agent to be running)
SELECT mcp_agents.tools.echo_agent('Hello from Databricks!');

-- Test calculator agent (requires agent to be running)
SELECT mcp_agents.tools.calculator_agent('add 5 and 3');
SELECT mcp_agents.tools.calculator_agent('multiply 10 by 4');

-- Test Epic FHIR stub (always works - local stub data)
SELECT mcp_agents.tools.epic_patient_search('Argonaut', 'Jason', NULL);
SELECT mcp_agents.tools.epic_patient_search('Smith', NULL, NULL);
```

### 3b. Python

```python
from src.agents.databricks import DatabricksMCPAgent

agent = DatabricksMCPAgent(catalog="mcp_agents", schema="tools")

# Call echo agent
result = agent.call_function("echo_agent", message="Hello from Python!")
print(result)

# Call calculator agent
result = agent.call_function("calculator_agent", expression="add 10 and 5")
print(result)

# Search Epic FHIR (stub)
result = agent.call_function("epic_patient_search", family_name="Argonaut")
print(result)
```

### 3c. curl

```bash
# Get token
TOKEN=$(databricks auth token | jq -r '.access_token')

# Call echo agent
curl -X POST "${DATABRICKS_HOST}/api/2.0/mcp/functions/mcp_agents/tools/echo_agent" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/call",
    "params": {"name": "echo_agent", "arguments": {"message": "Hello via MCP!"}}
  }'

# Call calculator agent
curl -X POST "${DATABRICKS_HOST}/api/2.0/mcp/functions/mcp_agents/tools/calculator_agent" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/call",
    "params": {"name": "calculator_agent", "arguments": {"expression": "multiply 25 by 4"}}
  }'

# Search Epic FHIR (stub)
curl -X POST "${DATABRICKS_HOST}/api/2.0/mcp/functions/mcp_agents/tools/epic_patient_search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/call",
    "params": {"name": "epic_patient_search", "arguments": {"family_name": "Argonaut"}}
  }'
```

---

## Step 4: Test from Azure AI Foundry

For detailed setup instructions with OAuth authentication, see **[foundry/README.md](foundry/README.md)**.

### 4a. Python MCP Client

```python
from src.agents.foundry import FoundryMCPClient

client = FoundryMCPClient(
    workspace_url="https://<workspace>.azuredatabricks.net",
    catalog="mcp_agents",
    schema="tools"
)

# List available tools
tools = client.list_tools()
for t in tools:
    print(f"  {t['name']}: {t.get('description', '')}")

# Call echo agent
result = client.call_tool("echo_agent", {"message": "Hello from Foundry!"})
print(result.content)

# Call calculator agent
result = client.call_tool("calculator_agent", {"expression": "add 15 and 27"})
print(result.content)

# Search patients
result = client.call_tool("epic_patient_search", {"family_name": "Argonaut"})
print(result.content)
```

### 4b. Azure CLI

```bash
# Get token for Databricks (Azure)
TOKEN=$(az account get-access-token \
  --resource 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d \
  -o tsv --query accessToken)

# Call echo agent
curl -X POST "https://<workspace>.azuredatabricks.net/api/2.0/mcp/functions/mcp_agents/tools/echo_agent" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"echo_agent","arguments":{"message":"Hello from Foundry!"}}}'

# Search Epic FHIR (stub)
curl -X POST "https://<workspace>.azuredatabricks.net/api/2.0/mcp/functions/mcp_agents/tools/epic_patient_search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"epic_patient_search","arguments":{"family_name":"Smith"}}}'
```

---

## Step 5: Test Access Control

Unity Catalog enforces who can execute MCP tools.

### Grant Access

```sql
-- Grant to a user
GRANT EXECUTE ON FUNCTION mcp_agents.tools.echo_agent TO `alice@company.com`;
GRANT EXECUTE ON FUNCTION mcp_agents.tools.calculator_agent TO `alice@company.com`;
GRANT EXECUTE ON FUNCTION mcp_agents.tools.epic_patient_search TO `alice@company.com`;

-- Grant to a group
GRANT EXECUTE ON FUNCTION mcp_agents.tools.echo_agent TO `data-science-team`;

-- Grant to a service principal
GRANT EXECUTE ON FUNCTION mcp_agents.tools.epic_patient_search TO `my-app-sp`;
```

### Revoke Access

```sql
REVOKE EXECUTE ON FUNCTION mcp_agents.tools.calculator_agent FROM `intern-group`;
```

### View Permissions

```sql
SELECT grantee, privilege
FROM system.information_schema.function_privileges
WHERE function_catalog = 'mcp_agents'
  AND function_schema = 'tools';
```

### Test Denied Access

A user without EXECUTE permission receives `403 Forbidden`.

---

## Step 6: Wrap Agents as UC Functions

The core pattern: **Any agent → UC Function → MCP Tool**

### Example: Wrap a Custom Agent

```sql
CREATE OR REPLACE FUNCTION mcp_agents.tools.my_agent(
    message STRING COMMENT 'Message to send to the agent'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: My custom agent'
AS $$
import json
import requests

def my_agent(message: str) -> str:
    # Your agent logic here
    # - Call an LLM
    # - Query a database
    # - Call an external API

    response = f"Processed: {message}"

    return json.dumps({
        "response": response,
        "status": "success"
    })

return my_agent(message)
$$;
```

### Example: Wrap an Azure AI Foundry Agent

```sql
CREATE OR REPLACE FUNCTION mcp_agents.tools.call_foundry_agent(
    agent_name STRING COMMENT 'Name of the Foundry agent',
    message STRING COMMENT 'Message to send'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: Call an Azure AI Foundry agent'
AS $$
import json
import os
import requests

foundry_endpoint = os.environ.get("FOUNDRY_ENDPOINT")
token = os.environ.get("AZURE_TOKEN")

response = requests.post(
    f"{foundry_endpoint}/agents/{agent_name}/invoke",
    headers={"Authorization": f"Bearer {token}"},
    json={"messages": [{"role": "user", "content": message}]}
)

return json.dumps(response.json())
$$;
```

---

## Step 7: Use UC Functions as MCP Tools

Once registered, UC Functions are automatically available as MCP tools.

### MCP Endpoints

| Tool | Endpoint |
|------|----------|
| `echo_agent` | `/api/2.0/mcp/functions/mcp_agents/tools/echo_agent` |
| `calculator_agent` | `/api/2.0/mcp/functions/mcp_agents/tools/calculator_agent` |
| `epic_patient_search` | `/api/2.0/mcp/functions/mcp_agents/tools/epic_patient_search` |

### From a Databricks Agent

```python
from src.agents.databricks import DatabricksMCPAgent

agent = DatabricksMCPAgent(catalog="mcp_agents", schema="tools")

# Use echo agent
response = agent.call_function("echo_agent", message="Hello!")

# Use calculator agent
result = agent.call_function("calculator_agent", expression="add 42 and 2")

# Search patients
result = agent.call_function("epic_patient_search", family_name="Smith")
```

### From a Foundry Agent

```python
from src.agents.foundry import FoundryMCPClient

client = FoundryMCPClient(
    workspace_url="https://<workspace>.azuredatabricks.net",
    catalog="mcp_agents",
    schema="tools"
)

result = client.call_tool("calculator_agent", {"expression": "add 100 and 200"})
result = client.call_tool("epic_patient_search", {"family_name": "Argonaut"})
```

---

## Step 8: Audit & Governance

Unity Catalog automatically logs all function executions.

### View Function Executions

```sql
SELECT
    event_time,
    user_identity.email as user,
    request_params.full_name_arg as function_name,
    response.status_code,
    source_ip_address
FROM system.access.audit
WHERE action_name = 'executeFunction'
  AND request_params.full_name_arg LIKE 'mcp_agents.tools.%'
ORDER BY event_time DESC
LIMIT 100;
```

### View Permission Grants

```sql
SELECT grantee, privilege, inherited_from
FROM system.information_schema.function_privileges
WHERE function_catalog = 'mcp_agents'
  AND function_schema = 'tools';
```

### Audit Log Example

```
┌───────────┬────────────────┬────────────────┬────────────────┐
│ Time      │ User           │ Function       │ Source IP      │
├───────────┼────────────────┼────────────────┼────────────────┤
│ 10:30:00  │ alice@corp.com │ echo           │ 10.0.0.5       │
│ 10:30:01  │ alice@corp.com │ calculator     │ 10.0.0.5       │
│ 10:30:05  │ bob@corp.com   │ echo           │ 10.0.0.8       │
│ 10:31:00  │ sp-foundry-app │ calculator     │ 52.168.1.100   │
└───────────┴────────────────┴────────────────┴────────────────┘
```

---

## Step 9: Test from Microsoft Teams

Use Microsoft Copilot Studio to connect Databricks MCP tools to Teams.

### 9a. Create Copilot Studio Agent

1. Go to [Copilot Studio](https://copilotstudio.microsoft.com)
2. Create a new **Custom Copilot**
3. Name it (e.g., "MCP Tools Agent")

### 9b. Add MCP Connection

1. Go to **Settings** → **Generative AI** → **Dynamic**
2. Click **Add knowledge** → **Model Context Protocol**
3. Configure:

| Setting | Value |
|---------|-------|
| Name | `Databricks MCP Tools` |
| Endpoint URL | `https://<workspace>.azuredatabricks.net/api/2.0/mcp/functions/mcp_agents/tools` |
| Authentication | `OAuth 2.0` |
| Client ID | Your Entra app registration client ID |
| Client Secret | Your app registration secret |
| Token URL | `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token` |
| Scope | `2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default` |

4. Click **Test Connection**

### 9c. Publish to Teams

1. Go to **Channels** → **Microsoft Teams**
2. Click **Turn on Teams**
3. Click **Open in Teams** to test

### 9d. Test in Teams

```
You: Echo "Hello from Teams!"

Copilot: [Calling MCP tool: echo]
         {"echo": "Hello from Teams!", "timestamp": "2025-02-07T10:30:00", ...}

You: What is 25 times 4?

Copilot: [Calling MCP tool: calculator]
         {"expression": "25 * 4", "result": 100, ...}

You: Calculate (100 + 50) divided by 3

Copilot: [Calling MCP tool: calculator]
         {"expression": "(100 + 50) / 3", "result": 50.0, ...}
```

---

## Agent Bricks: Multi-Agent Orchestration

[Agent Bricks](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/multi-agent-supervisor) is Databricks' framework for building production AI agents with minimal code. It provides pre-built patterns—like the **Multi-Agent Supervisor**—that handle the complexity of orchestrating multiple tools and agents.

### What is Agent Bricks?

Agent Bricks takes a declarative approach to agent development. Instead of writing orchestration logic, you describe what you want and Agent Bricks handles:

- **Automatic optimization** — Improves agent coordination based on natural language feedback from subject matter experts
- **Task delegation** — Routes requests to the appropriate tools or sub-agents
- **Parallel execution** — Runs independent operations concurrently
- **Result synthesis** — Combines outputs from multiple tools into coherent responses
- **Access control** — Enforces Unity Catalog permissions so users only access what they're authorized for

### How It Fits This Framework

The UC Functions you create (echo, calculator, custom agents) become building blocks that Agent Bricks can orchestrate:

```
┌─────────────────────────────────────────────────────────────────┐
│                   Multi-Agent Supervisor                        │
│                      (Agent Bricks)                             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
    ┌───────────┐     ┌───────────┐     ┌───────────┐
    │echo_agent │     │calculator_│     │epic_      │
    │ UC Func   │     │agent      │     │patient_   │
    │           │     │ UC Func   │     │search     │
    └─────┬─────┘     └─────┬─────┘     └───────────┘
          │                 │                 │
          ▼                 ▼                 │
    ┌───────────┐     ┌───────────┐           │
    │Echo Agent │     │Calculator │    (Stub API)
    │ DBX App   │     │  DBX App  │
    │ MLflow    │     │  MLflow   │
    └───────────┘     └───────────┘
          │                 │                 │
          └─────────────────┴─────────────────┘
                            │
                    Databricks Managed MCP
```

### Getting Started

1. Register your UC Functions as MCP tools (Steps 1-2 above)
2. Create a Multi-Agent Supervisor in Databricks
3. Add your UC Functions as sub-agents
4. Deploy — Agent Bricks creates a unified endpoint for your application

For detailed setup, see the [Agent Bricks documentation](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/multi-agent-supervisor).

---

## File Structure

```
├── apps/
│   ├── echo/                     # Echo Agent (Databricks App)
│   │   ├── agent.py              # MLflow ResponsesAgent implementation
│   │   ├── start_server.py       # AgentServer startup
│   │   ├── app.yaml              # Databricks App config
│   │   └── requirements.txt
│   └── calculator/               # Calculator Agent (Databricks App)
│       ├── agent.py              # MLflow ResponsesAgent implementation
│       ├── start_server.py       # AgentServer startup
│       ├── app.yaml              # Databricks App config
│       └── requirements.txt
├── src/
│   ├── agents/
│   │   ├── databricks/           # Databricks agents using MCP tools
│   │   └── foundry/              # Foundry MCP integration
│   └── mcp/
│       └── functions/            # UC Function definitions
├── notebooks/
│   └── register_uc_functions.py  # Register UC Functions (wrappers for agents)
├── infra/
│   ├── main.tf                   # Azure Databricks + AI Foundry
│   └── Makefile
├── tests/                        # Unit tests
├── .env.example                  # Configuration template
├── Makefile                      # Development commands
└── databricks.yml                # Databricks Asset Bundle config (apps + notebooks)
```

---

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make setup` | Create .env from template |
| `make deploy-infra` | Phase 1: Deploy Azure infrastructure (Databricks + Foundry) |
| `make deploy-uc` | Phase 2: Deploy UC resources + apps + notebook (after metastore assignment) |
| `make deploy-bundle` | Deploy bundle, start apps, update env, grant permissions |
| `make deploy-apps` | Deploy/redeploy agents as Databricks Apps |
| `make create-sp-secret` | Create OAuth secret for Service Principal |
| `make grant-sp-permission` | Grant SP permission on apps |
| `make destroy-infra` | Destroy Azure infrastructure |
| `make clean-bundle-state` | Clean Databricks bundle state (fixes stale state issues) |

---

## Quick Setup: Expose an Agent via MCP

To wrap a Databricks App agent as an MCP tool:

1. **Deploy infrastructure** — `make deploy-infra` then `make deploy-uc`
2. **Create Service Principal** — Terraform creates `mcp-interop-agent-caller` SP with OAuth secret
3. **Grant SP permission on app** — `CAN_USE` permission on your Databricks App
4. **Create HTTP Connection** — OAuth M2M connection using SP credentials from secret scope
5. **Register UC Function** — SQL function using `http_request()` with the connection
6. **Call via MCP** — `POST /api/2.0/mcp/functions/{catalog}/{schema}/{function}`

The notebook (`register_uc_functions.py`) handles steps 4-5 automatically after infrastructure is deployed.

---

## Known Limitations

| Limitation | Description | Status |
|------------|-------------|--------|
| **OAuth token generation in notebooks** | Notebooks cannot programmatically generate OAuth secrets for Service Principals. Secrets must be created via Terraform/CLI. | Tracked internally |
| **HTTP Connections block U2M** | UC HTTP Connections using `http_request()` in SQL do not support User-to-Machine (U2M) authentication. Use OAuth M2M (Service Principal) instead. | Platform limitation |
| **SP permission via CLI** | Granting app permissions to SPs requires using the application_id as `service_principal_name` in API calls. | Workaround documented |

---

## References

- [Databricks Managed MCP](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp)
- [Agent Bricks: Multi-Agent Supervisor](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/multi-agent-supervisor)
- [Azure AI Foundry MCP](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools-classic/model-context-protocol)
- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [Unity Catalog HTTP Connections](https://learn.microsoft.com/en-us/azure/databricks/query-federation/http)
- [Unity Catalog Audit Logs](https://docs.databricks.com/en/administration-guide/account-settings/audit-logs.html)
