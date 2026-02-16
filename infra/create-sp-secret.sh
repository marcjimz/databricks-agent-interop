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

# Configuration - SP name uses PREFIX from environment
PREFIX="${PREFIX:-mcp-agent-interop}"
SP_NAME="${PREFIX}-agent-caller"
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

# Create secret scope if it doesn't exist
echo "Checking secret scope: $SECRET_SCOPE"
if ! databricks secrets list-scopes --output json 2>/dev/null | jq -e ".[] | select(.name == \"$SECRET_SCOPE\")" > /dev/null; then
    echo "Creating secret scope: $SECRET_SCOPE"
    databricks secrets create-scope "$SECRET_SCOPE"
fi

# Check if secrets already exist
EXISTING_SECRET=$(databricks secrets list --scope "$SECRET_SCOPE" --output json 2>/dev/null | jq -r ".[] | select(.key == \"$SECRET_KEY\") | .key" || echo "")
EXISTING_CLIENT_ID=$(databricks secrets list --scope "$SECRET_SCOPE" --output json 2>/dev/null | jq -r ".[] | select(.key == \"client-id\") | .key" || echo "")

if [ -n "$EXISTING_SECRET" ] && [ -n "$EXISTING_CLIENT_ID" ]; then
    echo "Secrets already exist in scope '$SECRET_SCOPE'. Skipping."
    echo "To regenerate, delete the scope first: databricks secrets delete-scope $SECRET_SCOPE"
    exit 0
fi

# Get access token - try databricks CLI first, fall back to Azure CLI
echo "Getting access token..."
TOKEN=""
if TOKEN_JSON=$(databricks auth token --host "$DATABRICKS_HOST" 2>/dev/null); then
    TOKEN=$(echo "$TOKEN_JSON" | jq -r '.access_token // empty')
fi
if [ -z "$TOKEN" ]; then
    echo "Databricks CLI token failed, trying Azure CLI..."
    TOKEN=$(az account get-access-token --resource 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d --query accessToken -o tsv 2>/dev/null) || true
fi
if [ -z "$TOKEN" ]; then
    echo "Error: Could not get access token. Try 'az login' or 'databricks auth login --host $DATABRICKS_HOST'"
    exit 1
fi
echo "Got access token"

# Create OAuth secret via API
echo "Creating OAuth secret for service principal..."
SECRET_RESPONSE=$(curl -s -X POST \
    "${DATABRICKS_HOST}/api/2.0/accounts/servicePrincipals/${SP_ID}/credentials/secrets" \
    -H "Authorization: Bearer $TOKEN" \
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

# Store both client-id and client-secret in Databricks secret scope
echo "Storing credentials in scope: $SECRET_SCOPE"
databricks secrets put-secret "$SECRET_SCOPE" "client-id" --string-value "$SP_APP_ID"
databricks secrets put-secret "$SECRET_SCOPE" "$SECRET_KEY" --string-value "$CLIENT_SECRET"

echo ""
echo "=== OAuth Secret Configuration Complete ==="
echo "Stored in $SECRET_SCOPE:"
echo "  - client-id: $SP_APP_ID"
echo "  - client-secret: (hidden)"
echo ""
echo "Next steps:"
echo "  1. Grant SP permission on app: databricks apps set-permission calculator-agent --permission CAN_USE --service-principal-name $SP_NAME"
echo "  2. Run the notebook to create HTTP Connection and UC functions"
