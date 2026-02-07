# Databricks Agent Interoperability Framework

![./static/img/dbx-banner.jpeg](./static/img/dbx-banner.jpeg)

A framework for **agent interoperability** on Databricks, where **Unity Catalog** is the heart for discovery, governance, and traceability. Wrap any agent—internal or external—as a UC Function and expose it via **MCP (Model Context Protocol)** for seamless access across platforms.

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
```

---

## Step 0: Configure Environment

Create your configuration file before running any commands.

```bash
# Create .env from template
make setup

# Edit .env with your values
```

### .env Configuration

```bash
# Required
TENANT_ID=your-azure-tenant-id
SUBSCRIPTION_ID=your-azure-subscription-id
DATABRICKS_HOST=https://your-workspace.azuredatabricks.net

# Unity Catalog
UC_CATALOG=mcp_agents
UC_SCHEMA=tools

# Optional - for metastore assignment
DATABRICKS_ACCOUNT_ID=your-databricks-account-id
UC_METASTORE_ID=your-metastore-id

# Optional - for Foundry integration
FOUNDRY_ENDPOINT=https://your-foundry.azure.com

# Infrastructure
LOCATION=eastus2
```

---

## Step 1: Deploy Infrastructure

Deploy Azure Databricks workspace and Azure AI Foundry.

```bash
# Deploy Azure resources
make deploy-infra

# Or with Unity Catalog metastore assignment
make deploy-infra-uc
```

### What Gets Deployed

| Resource | Purpose |
|----------|---------|
| Azure Databricks Workspace | Premium SKU with Unity Catalog |
| Azure AI Foundry | AI Hub + AI Services |
| Unity Catalog | `mcp_agents.tools` schema |
| SQL Warehouse | Serverless for function execution |

---

## Step 2: Register UC Functions as MCP Tools

UC Functions become MCP tools automatically via Databricks managed MCP servers.

### Option A: Run the Notebook

Import and run in Databricks:

```
notebooks/register_uc_functions.py
```

### Option B: Generate and Run SQL

```bash
# Generate registration SQL
make generate-sql

# View available functions
make list-functions
```

### Option C: Run SQL Directly

```sql
-- Create catalog and schema
CREATE CATALOG IF NOT EXISTS mcp_agents;
CREATE SCHEMA IF NOT EXISTS mcp_agents.tools;

-- Register echo function
CREATE OR REPLACE FUNCTION mcp_agents.tools.echo(
    message STRING COMMENT 'Message to echo back'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: Echo back the input message'
AS $$
import json
from datetime import datetime

return json.dumps({
    "echo": message,
    "timestamp": datetime.now().isoformat(),
    "source": "UC Function via Databricks Managed MCP"
})
$$;

-- Register calculator function
CREATE OR REPLACE FUNCTION mcp_agents.tools.calculator(
    expression STRING COMMENT 'Mathematical expression (e.g., "2 + 2")'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: Evaluate mathematical expressions'
AS $$
import json
import re
from datetime import datetime

if not re.match(r'^[0-9+\-*/().\\s]+$', expression):
    return json.dumps({"error": "Invalid expression"})

result = eval(expression)
return json.dumps({
    "expression": expression,
    "result": result,
    "timestamp": datetime.now().isoformat()
})
$$;
```

### Verify Registration

```sql
SHOW FUNCTIONS IN mcp_agents.tools;
```

---

## Step 3: Test from Databricks

### 3a. SQL

```sql
-- Test echo
SELECT mcp_agents.tools.echo('Hello from Databricks!');

-- Test calculator
SELECT mcp_agents.tools.calculator('2 + 2');
SELECT mcp_agents.tools.calculator('(10 + 5) * 3');
```

### 3b. Makefile

```bash
# Test echo via MCP
make test-echo

# Test calculator via MCP
make test-calculator

# Test both
make test
```

### 3c. Python

```python
from src.agents.databricks import DatabricksMCPAgent

agent = DatabricksMCPAgent(catalog="mcp_agents", schema="tools")

# Test echo
result = agent.echo("Hello from Python!")
print(result)

# Test calculator
result = agent.call_function("calculator", expression="100 / 4")
print(result)
```

### 3d. curl

```bash
# Get token
TOKEN=$(databricks auth token | jq -r '.access_token')

# Call echo
curl -X POST "${DATABRICKS_HOST}/api/2.0/mcp/functions/mcp_agents/tools/echo" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/call",
    "params": {"name": "echo", "arguments": {"message": "Hello via MCP!"}}
  }'

# Call calculator
curl -X POST "${DATABRICKS_HOST}/api/2.0/mcp/functions/mcp_agents/tools/calculator" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "tools/call",
    "params": {"name": "calculator", "arguments": {"expression": "25 * 4"}}
  }'
```

---

## Step 4: Test from Azure AI Foundry

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

# Call echo
result = client.call_tool("echo", {"message": "Hello from Foundry!"})
print(result.content)

# Call calculator
result = client.call_tool("calculator", {"expression": "15 + 27"})
print(result.content)
```

### 4b. Azure CLI

```bash
# Get token for Databricks (Azure)
TOKEN=$(az account get-access-token \
  --resource 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d \
  -o tsv --query accessToken)

# Call echo
curl -X POST "https://<workspace>.azuredatabricks.net/api/2.0/mcp/functions/mcp_agents/tools/echo" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"echo","arguments":{"message":"Hello from Foundry!"}}}'
```

---

## Step 5: Test Access Control

Unity Catalog enforces who can execute MCP tools.

### Grant Access

```sql
-- Grant to a user
GRANT EXECUTE ON FUNCTION mcp_agents.tools.echo TO `alice@company.com`;
GRANT EXECUTE ON FUNCTION mcp_agents.tools.calculator TO `alice@company.com`;

-- Grant to a group
GRANT EXECUTE ON FUNCTION mcp_agents.tools.echo TO `data-science-team`;

-- Grant to a service principal
GRANT EXECUTE ON FUNCTION mcp_agents.tools.calculator TO `my-app-sp`;
```

### Revoke Access

```sql
REVOKE EXECUTE ON FUNCTION mcp_agents.tools.calculator FROM `intern-group`;
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
| `echo` | `/api/2.0/mcp/functions/mcp_agents/tools/echo` |
| `calculator` | `/api/2.0/mcp/functions/mcp_agents/tools/calculator` |
| `call_foundry_agent` | `/api/2.0/mcp/functions/mcp_agents/tools/call_foundry_agent` |

### From a Databricks Agent

```python
from src.agents.databricks import DatabricksMCPAgent

agent = DatabricksMCPAgent(catalog="mcp_agents", schema="tools")

# Use echo
response = agent.echo("Hello!")

# Use calculator
result = agent.call_function("calculator", expression="42 * 2")
```

### From a Foundry Agent

```python
from src.agents.foundry import FoundryMCPClient

client = FoundryMCPClient(
    workspace_url="https://<workspace>.azuredatabricks.net",
    catalog="mcp_agents",
    schema="tools"
)

result = client.call_tool("calculator", {"expression": "100 + 200"})
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
    │   echo    │     │calculator │     │  foundry  │
    │ UC Func   │     │ UC Func   │     │ UC Func   │
    └───────────┘     └───────────┘     └───────────┘
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
├── src/
│   ├── agents/
│   │   ├── databricks/           # Databricks agents using MCP tools
│   │   └── foundry/              # Foundry MCP integration
│   └── mcp/
│       └── functions/            # UC Function definitions
├── notebooks/
│   └── register_uc_functions.py  # Register UC Functions in Databricks
├── infra/
│   ├── main.tf                   # Azure Databricks + AI Foundry
│   └── Makefile
├── tests/                        # Unit tests
├── .env.example                  # Configuration template
├── Makefile                      # Development commands
└── databricks.yml                # Databricks Asset Bundle config
```

---

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make setup` | Create .env from template |
| `make deploy-infra` | Deploy Azure infrastructure |
| `make generate-sql` | Generate UC Function registration SQL |
| `make list-functions` | List available MCP tools |
| `make test-echo` | Test echo function via MCP |
| `make test-calculator` | Test calculator function via MCP |
| `make test` | Run all MCP tests |

---

## References

- [Databricks Managed MCP](https://docs.databricks.com/aws/en/generative-ai/mcp/managed-mcp)
- [Agent Bricks: Multi-Agent Supervisor](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/multi-agent-supervisor)
- [Azure AI Foundry MCP](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools-classic/model-context-protocol)
- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [Unity Catalog Audit Logs](https://docs.databricks.com/en/administration-guide/account-settings/audit-logs.html)
