# Microsoft Copilot Studio Integration Guide

This guide explains how to integrate the A2A Gateway with Microsoft Copilot Studio for agent-to-agent communication.

## Overview

Microsoft Copilot Studio supports the A2A Protocol, enabling copilots to communicate with external agents. This gateway allows Copilot-hosted agents to access Databricks-managed agents through Unity Catalog connections with proper authorization.

### Architecture

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  Copilot Studio     │────▶│  A2A Gateway     │────▶│  Backend Agent      │
│  (User Copilot)     │     │  (Azure APIM)    │     │  (Your Service)     │
└─────────────────────┘     └──────────────────┘     └─────────────────────┘
         │                           │
         │ Entra ID OAuth            │ Token Exchange
         │ (Delegated Flow)          │ + UC Authorization
         └───────────────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │  Databricks UC   │
         │  (Permission)    │
         └──────────────────┘
```

## Prerequisites

1. **Microsoft Resources**:
   - Copilot Studio environment with agent-to-agent feature enabled
   - Entra ID app registration for OAuth
   - Azure API Management (APIM) with gateway deployed

2. **Databricks Configuration**:
   - Workspace with Unity Catalog enabled
   - Account-level OIDC federation with Entra ID
   - UC connections for target agents
   - Automatic identity provisioning enabled

3. **Network Requirements**:
   - Copilot must reach APIM gateway (public or private endpoint)
   - APIM must reach Databricks APIs and backend agents

## Authentication Flow

Copilot Studio uses delegated OAuth flow (U2M):

```
1. User interacts with Copilot
2. Copilot authenticates user via Entra ID (delegated)
3. Copilot calls A2A Gateway with user's Entra ID token
4. APIM validates Entra token (validate-azure-ad-token)
5. APIM exchanges Entra token for Databricks token
6. APIM checks UC USE_CONNECTION permission
7. Request proxied to backend agent with OBO context
```

## Setup Instructions

### 1. Deploy APIM Gateway

Deploy the A2A Gateway infrastructure:

```bash
cd infra/
terraform init
terraform apply \
  -var="environment=prod" \
  -var="entra_tenant_id=YOUR_TENANT_ID" \
  -var="databricks_host=https://your-workspace.databricks.azure.us"
```

### 2. Register Backend Agent in UC

Create a UC connection for your agent:

```bash
python scripts/create_agent_connection.py \
  --name weather-agent \
  --host https://weather-agent.azurewebsites.net \
  --base-path /a2a \
  --comment "Weather information agent for Copilot"
```

### 3. Grant Access Permissions

Grant USE_CONNECTION to users who will use Copilot:

```sql
-- Grant to all users in the workspace
GRANT USE CONNECTION ON CONNECTION `weather-agent-a2a` TO `account users`;

-- Or grant to specific group
GRANT USE CONNECTION ON CONNECTION `weather-agent-a2a` TO GROUP `copilot-users`;
```

### 4. Configure Copilot Studio Agent Tool

In Copilot Studio, add the A2A agent:

1. Open your copilot in Copilot Studio
2. Navigate to **Topics** > **Create** > **Custom**
3. Add an **Action** > **Agent-to-Agent**
4. Configure the connection:

   | Setting | Value |
   |---------|-------|
   | Name | Weather Agent |
   | Agent URL | `https://your-apim.azure-api.net/agents/weather-agent` |
   | Agent Card URL | `https://your-apim.azure-api.net/agents/weather-agent/.well-known/agent.json` |
   | Authentication | OAuth 2.0 (Delegated) |
   | Tenant ID | Your Entra tenant ID |
   | Client ID | Your app registration client ID |

5. Test the connection

### 5. Configure OAuth in Copilot

Set up OAuth authentication for your Copilot:

1. In Copilot Studio, go to **Settings** > **Security** > **Authentication**
2. Select **Authenticate with Microsoft**
3. Configure delegated permissions:
   - `User.Read` (for user identity)
   - Custom scopes for your gateway if needed

4. Test authentication flow

## API Endpoints

The gateway exposes these endpoints for Copilot:

### List Available Agents

```http
GET /agents
Authorization: Bearer {entra-token}
```

Response:
```json
{
  "agents": [
    {
      "name": "weather-agent",
      "description": "Weather information agent",
      "url": "/agents/weather-agent"
    }
  ],
  "user": "user@company.com",
  "total": 1
}
```

### Get Agent Card

```http
GET /agents/{name}/.well-known/agent.json
Authorization: Bearer {entra-token}
```

Response:
```json
{
  "name": "weather-agent",
  "url": "https://weather-agent.azurewebsites.net/a2a",
  "description": "Weather information agent",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "securitySchemes": {
    "bearer": {
      "type": "http",
      "scheme": "bearer"
    }
  }
}
```

### Send Message (JSON-RPC)

```http
POST /agents/{name}
Authorization: Bearer {entra-token}
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "msg-1",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"type": "text", "text": "What's the weather in Seattle?"}]
    }
  }
}
```

### Stream Response (SSE)

```http
POST /agents/{name}/stream
Authorization: Bearer {entra-token}
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": "stream-1",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"type": "text", "text": "Tell me a story"}]
    }
  }
}
```

## Example Copilot Topic

Create a topic that uses the A2A agent:

```yaml
# Topic: Get Weather
Trigger phrases:
  - "What's the weather"
  - "Weather forecast"
  - "Temperature in {location}"

Actions:
  - Action: Agent-to-Agent (weather-agent)
    Input:
      message: "Get weather for ${location}"
    Output: weatherResponse

  - Message: ${weatherResponse}
```

## User Context Propagation

The gateway passes user context to backend agents:

| Header | Description |
|--------|-------------|
| `X-User-Email` | Authenticated user's email from Entra token |
| `X-A2A-Gateway` | Gateway identifier (`apim`) |
| `X-Request-ID` | Correlation ID for tracing |
| `Authorization` | Databricks token (after exchange) |

Backend agents can use these headers for user-specific responses.

## Troubleshooting

### Copilot Shows "Connection Failed"

**Possible causes**:
1. APIM gateway URL incorrect
2. OAuth configuration mismatch
3. Token scope issues

**Solutions**:
- Verify gateway URL is accessible from Copilot
- Check Entra tenant ID matches gateway config
- Ensure delegated permissions are granted

### 401 Unauthorized Errors

**Possible causes**:
1. Entra token expired
2. Wrong tenant
3. Token exchange failed

**Solutions**:
- Check token expiration
- Verify Databricks federation with Entra ID
- Check APIM logs in Application Insights

### 403 Forbidden Errors

**Possible causes**:
1. User lacks USE_CONNECTION permission
2. Connection not found
3. User not provisioned in Databricks

**Solutions**:
- Grant USE_CONNECTION to user/group
- Verify connection name ends with `-a2a`
- Check automatic identity provisioning in Databricks

### Slow Response Times

**Possible causes**:
1. Token exchange latency
2. Backend agent performance
3. APIM cold start (Consumption tier)

**Solutions**:
- Use APIM Developer or higher tier
- Enable response caching where appropriate
- Monitor backend agent performance

## Security Best Practices

1. **Least Privilege**: Grant USE_CONNECTION only to users who need it
2. **Token Validation**: Never disable token validation in production
3. **Audit Logging**: Enable Application Insights for all requests
4. **Private Endpoints**: Use VNet integration for production
5. **Rotation**: Rotate any static tokens regularly

## Monitoring

### Application Insights Queries

```kusto
// Copilot agent requests
traces
| where message contains "a2a-gateway"
| where customDimensions["auth.type"] == "entra-oauth-u2m"
| summarize count() by bin(timestamp, 1h), tostring(customDimensions["agent.name"])
| render timechart

// Error rate by agent
traces
| where message contains "Request error"
| summarize count() by tostring(customDimensions["agent.name"])
| order by count_ desc
```

### Key Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| Token Exchange Success Rate | % of successful exchanges | < 99% |
| Request Latency P95 | 95th percentile latency | > 2s |
| 4xx Error Rate | Client error rate | > 5% |
| 5xx Error Rate | Server error rate | > 1% |

## Related Documentation

- [Copilot Studio A2A](https://learn.microsoft.com/en-us/microsoft-copilot-studio/add-agent-agent-to-agent)
- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [Databricks Unity Catalog](https://docs.databricks.com/en/data-governance/unity-catalog/index.html)
- [Azure APIM Authentication](https://learn.microsoft.com/en-us/azure/api-management/authentication-authorization-overview)
