#!/bin/bash
#
# Create a Unity Catalog HTTP connection for an Azure-hosted A2A agent.
# This registers the agent with the Databricks A2A Gateway for discovery.
#
# Usage:
#   ./create-uc-connection.sh <agent-name> <agent-url> [auth-type]
#
# Arguments:
#   agent-name  Name for the agent (will be suffixed with -a2a)
#   agent-url   Base URL of the agent (e.g., https://agent.azurecontainerapps.io)
#   auth-type   Optional: "databricks" (default), "static:<token>", or "oauth"
#
# Examples:
#   # Same tenant (Entra ID pass-through)
#   ./create-uc-connection.sh azure-demo https://azure-demo-agent.azurecontainerapps.io
#
#   # Static bearer token
#   ./create-uc-connection.sh external-agent https://external.example.com static:my-api-key
#
#   # OAuth M2M (will prompt for credentials)
#   ./create-uc-connection.sh partner-agent https://partner.example.com oauth

set -e

# Parse arguments
AGENT_NAME="${1:-}"
AGENT_URL="${2:-}"
AUTH_TYPE="${3:-databricks}"

if [ -z "$AGENT_NAME" ] || [ -z "$AGENT_URL" ]; then
    echo "Usage: $0 <agent-name> <agent-url> [auth-type]"
    echo ""
    echo "Arguments:"
    echo "  agent-name  Name for the agent (will be suffixed with -a2a)"
    echo "  agent-url   Base URL of the agent"
    echo "  auth-type   Optional: 'databricks' (default), 'static:<token>', or 'oauth'"
    echo ""
    echo "Examples:"
    echo "  $0 azure-demo https://azure-demo-agent.azurecontainerapps.io"
    echo "  $0 external-agent https://external.example.com static:my-api-key"
    exit 1
fi

# Ensure connection name ends with -a2a
CONNECTION_NAME="${AGENT_NAME%-a2a}-a2a"

echo "=== Creating UC Connection for A2A Agent ==="
echo "Connection Name: ${CONNECTION_NAME}"
echo "Agent URL: ${AGENT_URL}"
echo "Auth Type: ${AUTH_TYPE}"
echo ""

# Build connection options based on auth type
if [[ "$AUTH_TYPE" == "databricks" ]]; then
    # Same tenant - Entra ID pass-through
    OPTIONS=$(cat <<EOF
{
  "host": "${AGENT_URL}",
  "base_path": "/.well-known/agent.json",
  "bearer_token": "databricks"
}
EOF
)
elif [[ "$AUTH_TYPE" == static:* ]]; then
    # Static bearer token
    TOKEN="${AUTH_TYPE#static:}"
    OPTIONS=$(cat <<EOF
{
  "host": "${AGENT_URL}",
  "base_path": "/.well-known/agent.json",
  "bearer_token": "${TOKEN}"
}
EOF
)
elif [[ "$AUTH_TYPE" == "oauth" ]]; then
    # OAuth M2M - prompt for credentials
    echo "OAuth M2M Configuration:"
    read -p "  Client ID: " CLIENT_ID
    read -s -p "  Client Secret: " CLIENT_SECRET
    echo ""
    read -p "  Token Endpoint: " TOKEN_ENDPOINT
    read -p "  OAuth Scope (optional): " OAUTH_SCOPE

    OPTIONS=$(cat <<EOF
{
  "host": "${AGENT_URL}",
  "base_path": "/.well-known/agent.json",
  "client_id": "${CLIENT_ID}",
  "client_secret": "${CLIENT_SECRET}",
  "token_endpoint": "${TOKEN_ENDPOINT}"$([ -n "$OAUTH_SCOPE" ] && echo ",
  \"oauth_scope\": \"${OAUTH_SCOPE}\"")
}
EOF
)
else
    echo "Error: Unknown auth type '${AUTH_TYPE}'"
    echo "Valid types: databricks, static:<token>, oauth"
    exit 1
fi

# Check if connection already exists
if databricks connections get "${CONNECTION_NAME}" &>/dev/null; then
    echo "Connection '${CONNECTION_NAME}' already exists."
    read -p "Do you want to delete and recreate it? (y/N): " CONFIRM
    if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
        echo "Deleting existing connection..."
        databricks connections delete "${CONNECTION_NAME}"
    else
        echo "Aborted."
        exit 0
    fi
fi

# Create the connection
echo "Creating connection..."
databricks connections create --json "$(cat <<EOF
{
  "name": "${CONNECTION_NAME}",
  "connection_type": "HTTP",
  "options": ${OPTIONS},
  "comment": "Azure A2A agent: ${AGENT_NAME}"
}
EOF
)"

echo ""
echo "✅ Connection created: ${CONNECTION_NAME}"
echo ""

# Verify agent card is accessible
echo "Verifying agent card..."
AGENT_CARD_URL="${AGENT_URL}/.well-known/agent.json"
if curl -sf "${AGENT_CARD_URL}" > /dev/null 2>&1; then
    echo "✅ Agent card accessible at ${AGENT_CARD_URL}"
    echo ""
    echo "Agent card contents:"
    curl -s "${AGENT_CARD_URL}" | jq '.' 2>/dev/null || curl -s "${AGENT_CARD_URL}"
else
    echo "⚠️  Could not fetch agent card from ${AGENT_CARD_URL}"
    echo "   Agent may require authentication or may not be running yet."
fi

echo ""
echo "=== Next Steps ==="
echo ""
echo "1. Grant access to users:"
echo "   databricks grants update connection \"${CONNECTION_NAME}\" \\"
echo "     --json '{\"changes\": [{\"add\": [\"USE_CONNECTION\"], \"principal\": \"user@company.com\"}]}'"
echo ""
echo "2. Grant access to gateway service principal:"
echo "   GATEWAY_SP=\$(databricks apps get \${PREFIX}-a2a-gateway --output json | jq -r '.service_principal_client_id')"
echo "   databricks grants update connection \"${CONNECTION_NAME}\" \\"
echo "     --json \"{\\\"changes\\\": [{\\\"add\\\": [\\\"USE_CONNECTION\\\"], \\\"principal\\\": \\\"\\\${GATEWAY_SP}\\\"}]}\""
echo ""
echo "3. Test discovery via gateway:"
echo "   curl -s \"\${GATEWAY_URL}/api/agents\" -H \"Authorization: Bearer \${TOKEN}\" | jq"
