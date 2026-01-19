# Databricks A2A Gateway

A2A protocol gateway for Databricks. Discovers agents via UC connections (`*-a2a`), authorizes via connection access.

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

## Structure

```
app/                    → Gateway
src/agents/echo/        → Echo agent
src/agents/calculator/  → Calculator agent
notebooks/              → Setup & test notebooks
databricks.yml          → DAB config
Makefile                → Deploy commands
```
