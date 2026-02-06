# Microsoft Azure AI Foundry Integration Guide

This guide explains how to integrate the A2A Gateway with Microsoft Azure AI Foundry for agent-to-agent communication.

## Overview

Azure AI Foundry supports the A2A Protocol for agent-to-agent communication. This gateway enables Foundry-hosted agents to communicate with Databricks-managed agents through Unity Catalog connections.

### Architecture

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  Azure AI Foundry   │────▶│  A2A Gateway     │────▶│  Backend Agent      │
│  (Agent Host)       │     │  (Azure APIM)    │     │  (Your Service)     │
└─────────────────────┘     └──────────────────┘     └─────────────────────┘
         │                           │
         │ Entra ID OAuth            │ Token Exchange
         └───────────────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │  Databricks UC   │
         │  (Authorization) │
         └──────────────────┘
```

## Prerequisites

1. **Azure Resources**:
   - Azure AI Foundry project
   - Azure API Management (APIM) instance with gateway deployed
   - Entra ID tenant federated with Databricks

2. **Databricks Configuration**:
   - Workspace with Unity Catalog enabled
   - OIDC federation with Entra ID tenant
   - UC connections for target agents

3. **Network Access**:
   - Foundry agents must reach APIM gateway endpoint
   - APIM must reach Databricks workspace APIs
   - APIM must reach backend agent endpoints

## Authentication Flow

The A2A Gateway supports User-to-Machine (U2M) authentication with Entra ID tokens:

```
1. Foundry agent authenticates user via Entra ID OAuth
2. Foundry passes Entra ID token in Authorization header
3. APIM validates token using validate-azure-ad-token policy
4. APIM exchanges Entra token for Databricks token (RFC 8693)
5. APIM uses Databricks token to check UC permissions
6. Request is proxied to backend agent
```

### Supported Authentication Types

Foundry supports several authentication options. For this gateway, use:

| Auth Type | Configuration | Recommended |
|-----------|--------------|-------------|
| OAuth2 Custom | Custom OAuth flow | **Yes** |
| API Key | Static key header | No (no user context) |
| None | No authentication | No (insecure) |

## Setup Instructions

### 1. Configure APIM Gateway

Deploy the APIM gateway with Terraform:

```bash
cd infra/
terraform init
terraform apply -var-file=../config/environments/dev.yaml
```

### 2. Create UC Connection for Agent

Register your backend agent as a UC connection:

```bash
# Using provided script
python scripts/create_agent_connection.py \
  --name my-agent \
  --host https://my-agent-backend.azurewebsites.net \
  --base-path /a2a \
  --bearer-token databricks

# Or via Databricks CLI
databricks connections create \
  --name my-agent-a2a \
  --connection-type HTTP \
  --options '{
    "host": "https://my-agent-backend.azurewebsites.net",
    "base_path": "/a2a",
    "port": "443",
    "bearer_token": "databricks"
  }'
```

### 3. Grant Access to Users

Grant USE_CONNECTION to users who should access the agent:

```sql
-- Grant to specific user
GRANT USE CONNECTION ON CONNECTION `my-agent-a2a` TO `user@example.com`;

-- Grant to group
GRANT USE CONNECTION ON CONNECTION `my-agent-a2a` TO GROUP `data-scientists`;

-- Grant to all workspace users (not recommended for production)
GRANT USE CONNECTION ON CONNECTION `my-agent-a2a` TO `account users`;
```

### 4. Configure Foundry Agent Tool

In Azure AI Foundry, add your agent as an A2A tool:

1. Navigate to your Foundry project
2. Go to **Tools** > **Add Tool** > **Agent-to-Agent**
3. Configure the connection:

   ```yaml
   Name: My Databricks Agent
   URL: https://your-apim-gateway.azure-api.net/agents/my-agent

   Authentication:
     Type: OAuth2 Custom
     Token URL: https://login.microsoftonline.com/{tenant-id}/oauth2/v2.0/token
     Client ID: {your-entra-app-client-id}
     Scope: api://{databricks-resource-id}/.default

   Agent Card URL: https://your-apim-gateway.azure-api.net/agents/my-agent/.well-known/agent.json
   ```

### 5. Test the Integration

Test agent discovery:

```bash
# Get agent list
curl -H "Authorization: Bearer $ENTRA_TOKEN" \
  https://your-apim-gateway.azure-api.net/agents

# Get agent card
curl -H "Authorization: Bearer $ENTRA_TOKEN" \
  https://your-apim-gateway.azure-api.net/agents/my-agent/.well-known/agent.json

# Send message
curl -X POST \
  -H "Authorization: Bearer $ENTRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "Hello from Foundry!"}]
      }
    }
  }' \
  https://your-apim-gateway.azure-api.net/agents/my-agent
```

## Agent Card Format

The gateway generates A2A-compliant agent cards automatically from UC connections:

```json
{
  "name": "my-agent",
  "url": "https://my-agent-backend.azurewebsites.net/a2a",
  "description": "My backend agent",
  "version": "1.0.0",
  "securitySchemes": {
    "bearer": {
      "type": "http",
      "scheme": "bearer",
      "bearerFormat": "JWT",
      "description": "Databricks OAuth token (same tenant)"
    }
  },
  "security": [{"bearer": []}],
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"]
}
```

## Streaming Support

The gateway supports Server-Sent Events (SSE) streaming:

```bash
# Stream endpoint
curl -X POST \
  -H "Authorization: Bearer $ENTRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "stream-1",
    "method": "message/stream",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "Stream a response"}]
      }
    }
  }' \
  https://your-apim-gateway.azure-api.net/agents/my-agent/stream
```

## Troubleshooting

### Common Issues

#### 401 Unauthorized

**Cause**: Entra ID token is invalid or expired.

**Solution**:
- Verify token is valid and not expired
- Check Entra tenant ID matches gateway configuration
- Ensure user is in the correct Entra tenant

#### Token Exchange Failed

**Cause**: Databricks workspace not federated with Entra ID.

**Solution**:
- Verify Databricks account is federated with your Entra tenant
- Check user exists in Databricks with automatic provisioning
- Verify OIDC configuration in Databricks account settings

#### 403 Forbidden

**Cause**: User lacks USE_CONNECTION permission.

**Solution**:
- Grant USE_CONNECTION on the agent's UC connection
- Check user's Databricks identity matches their Entra ID

#### 404 Not Found

**Cause**: Agent connection doesn't exist.

**Solution**:
- Verify UC connection exists with `-a2a` suffix
- Check connection is in correct catalog/schema
- Verify connection is HTTP type

### Debug Headers

Check response headers for debugging:

```
X-A2A-Gateway: apim          # Confirms request went through gateway
X-User-Email: user@...       # Shows authenticated user
X-Request-ID: req-...        # Correlation ID for tracing
```

### Application Insights

If tracing is configured, query logs in Application Insights:

```kusto
traces
| where message contains "a2a-gateway"
| where customDimensions["request.id"] == "your-request-id"
| order by timestamp asc
```

## Security Considerations

1. **Token Handling**: Tokens are exchanged server-side and never exposed to clients
2. **UC Authorization**: All access is controlled via USE_CONNECTION privilege
3. **Audit Logging**: All requests are traced via Application Insights
4. **Network Security**: Use Private Endpoints for production deployments

## Related Documentation

- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [Azure AI Foundry A2A Docs](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/agent-to-agent)
- [Databricks OIDC Federation](https://docs.databricks.com/en/administration-guide/users-groups/oidc-federation.html)
- [APIM validate-azure-ad-token](https://learn.microsoft.com/en-us/azure/api-management/validate-azure-ad-token-policy)
