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
| **Sample Agents** | Echo and Calculator agents for testing (Databricks Apps) |

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

## Quick Start

### 1. Configure

```bash
cp config/.env.example config/.env
# Edit config/.env with your values
```

### 2. Deploy

```bash
make deploy          # Deploy APIM gateway
make deploy-agents   # Deploy echo/calculator agents
```

### 3. Register & Grant Access

```bash
make register-agents USER=marcin.jimenez@databricks.com
```

### 4. Test

```bash
make test-agents
```

## Registering Other Agents

```bash
# External agent (Foundry, third-party A2A services)
make register-external NAME=foundry-agent HOST=https://foundry-agent.example.com

# External agent with static bearer token
make register-external NAME=external HOST=https://api.example.com TOKEN=secret-token

# Custom registration (specify all options)
make register NAME=custom HOST=https://... BASE_PATH=/api/v1/a2a TOKEN=xxx
```

## Commands

| Command | Description |
|---------|-------------|
| `make deploy` | Deploy APIM gateway |
| `make deploy-agents` | Deploy echo/calculator sample agents |
| `make register-agents USER=x` | Register deployed agents + grant access |
| `make test-agents` | Test echo and calculator via gateway |
| `make status` | Show gateway URL and agent URLs |
| `make destroy` | Tear down APIM infrastructure |
| `make destroy-agents` | Tear down Databricks agents |
| `make register-databricks NAME=x HOST=y` | Register Databricks agent (token passthrough) |
| `make register-external NAME=x HOST=y` | Register external agent |
| `make grant NAME=x USER=y` | Grant access to user |
| `make revoke NAME=x USER=y` | Revoke access |

## Gateway Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agents` | GET | List accessible agents |
| `/agents/{name}` | GET | Get agent info |
| `/agents/{name}/.well-known/agent.json` | GET | Get A2A agent card |
| `/agents/{name}` | POST | A2A JSON-RPC proxy |
| `/agents/{name}/stream` | POST | A2A streaming (SSE) |

## Integration Guides

| Platform | Guide |
|----------|-------|
| Azure AI Foundry | [docs/integration/FOUNDRY.md](docs/integration/FOUNDRY.md) |
| Microsoft Copilot Studio | [docs/integration/COPILOT.md](docs/integration/COPILOT.md) |
