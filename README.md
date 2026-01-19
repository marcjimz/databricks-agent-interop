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
| `GET /health` | Health check |
| `GET /.well-known/agent.json` | Gateway's A2A agent card |
| `GET /api/agents` | List accessible agents |
| `GET /api/agents/{name}` | Get agent info |
| `POST /api/agents/{name}/message` | Send JSON-RPC message |
| `POST /api/agents/{name}/stream` | SSE streaming |

**Demo Agents** (`src/agents/`)
- Echo Agent - Simple echo back for testing
- Calculator Agent - Arithmetic with LangChain tools

**Notebooks:**
1. `01_deploy_apps.py` - Deploy via DAB
2. `02_register_agents.py` - Create UC connections
3. `03_test_interop.py` - Test A2A interoperability

## Prerequisites

- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) installed and authenticated (`databricks auth login`)
- `make`

## Deploy

```bash
make deploy
```

Custom prefix:
```bash
make deploy PREFIX=marcin
```

Check status:
```bash
make status
```

Stop apps:
```bash
make stop
```

Destroy:
```bash
make destroy
```

## Register Agents

```sql
CREATE CONNECTION `echo-a2a` TYPE HTTP
OPTIONS (url = 'https://<echo-agent-url>');

GRANT USE CONNECTION ON CONNECTION `echo-a2a` TO `users`;
```

