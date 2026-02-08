#!/bin/bash
# =============================================================================
# Create OAuth Secret for Service Principal
# =============================================================================
# This script creates an OAuth secret for the mcp-interop-agent-caller SP
# and stores it in the Databricks secret scope.
#
# Prerequisites:
#   - Databricks CLI configured with workspace access
#   - DATABRICKS_HOST environment variable set
#   - Service principal already created by Terraform
#
# Usage:
#   ./create-sp-secret.sh
# =============================================================================

set -euo pipefail

# Configuration
SP_NAME="mcp-interop-agent-caller"
SECRET_SCOPE="mcp-agent-oauth"
SECRET_KEY="client-secret"

echo "=== Creating OAuth Secret for Service Principal ==="

# Check prerequisites
if [ -z "${DATABRICKS_HOST:-}" ]; then
    echo "Error: DATABRICKS_HOST not set"
    exit 1
fi

echo "Workspace: $DATABRICKS_HOST"

# Get the service principal ID
echo "Looking up service principal: $SP_NAME"
SP_JSON=$(databricks service-principals list --output json 2>/dev/null | jq -r ".[] | select(.displayName == \"$SP_NAME\")")

if [ -z "$SP_JSON" ]; then
    echo "Error: Service principal '$SP_NAME' not found. Run 'make deploy-uc' first."
    exit 1
fi

SP_ID=$(echo "$SP_JSON" | jq -r '.id')
SP_APP_ID=$(echo "$SP_JSON" | jq -r '.applicationId')

echo "Found SP: id=$SP_ID, application_id=$SP_APP_ID"

# Check if secret scope exists
echo "Checking secret scope: $SECRET_SCOPE"
if ! databricks secrets list-scopes --output json 2>/dev/null | jq -e ".[] | select(.name == \"$SECRET_SCOPE\")" > /dev/null; then
    echo "Error: Secret scope '$SECRET_SCOPE' not found. Run 'make deploy-uc' first."
    exit 1
fi

# Check if secret already exists
EXISTING_SECRET=$(databricks secrets list --scope "$SECRET_SCOPE" --output json 2>/dev/null | jq -r ".[] | select(.key == \"$SECRET_KEY\") | .key" || echo "")

if [ -n "$EXISTING_SECRET" ]; then
    echo "Secret '$SECRET_KEY' already exists in scope '$SECRET_SCOPE'"
    read -p "Do you want to regenerate it? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Keeping existing secret."
        exit 0
    fi
fi

# Create OAuth secret via API
echo "Creating OAuth secret for service principal..."
SECRET_RESPONSE=$(curl -s -X POST \
    "${DATABRICKS_HOST}/api/2.0/accounts/servicePrincipals/${SP_ID}/credentials/secrets" \
    -H "Authorization: Bearer $(databricks auth token --host "$DATABRICKS_HOST" | jq -r '.access_token')" \
    -H "Content-Type: application/json")

# Check for errors
if echo "$SECRET_RESPONSE" | jq -e '.error_code' > /dev/null 2>&1; then
    echo "Error creating secret:"
    echo "$SECRET_RESPONSE" | jq .
    exit 1
fi

# Extract the secret value
CLIENT_SECRET=$(echo "$SECRET_RESPONSE" | jq -r '.secret')

if [ -z "$CLIENT_SECRET" ] || [ "$CLIENT_SECRET" = "null" ]; then
    echo "Error: Failed to extract secret from response"
    echo "$SECRET_RESPONSE" | jq .
    exit 1
fi

echo "OAuth secret created successfully"

# Store in Databricks secret scope
echo "Storing secret in scope: $SECRET_SCOPE"
databricks secrets put-secret "$SECRET_SCOPE" "$SECRET_KEY" --string-value "$CLIENT_SECRET"

echo ""
echo "=== OAuth Secret Configuration Complete ==="
echo "Client ID (application_id): $SP_APP_ID"
echo "Secret stored in: $SECRET_SCOPE/$SECRET_KEY"
echo ""
echo "Next steps:"
echo "  1. Grant SP permission on app: databricks apps set-permission calculator-agent --permission CAN_USE --service-principal-name $SP_NAME"
echo "  2. Run the notebook to create HTTP Connection and UC functions"
