#!/bin/bash
# Import existing Databricks resources into Terraform state
# Run this before deploy-uc if state gets out of sync

set -e

TF_VARS="-var=tenant_id=${TENANT_ID} -var=subscription_id=${SUBSCRIPTION_ID} -var=location=${LOCATION} -var=prefix=${PREFIX} -var=resource_group_name=${RESOURCE_GROUP} -var=deploy_uc=true"

echo "=== Importing Existing Databricks Resources ==="

# Function to import if resource exists
import_if_exists() {
    local tf_resource=$1
    local db_id=$2
    local check_cmd=$3

    # Check if already in state
    if terraform state show "$tf_resource" &>/dev/null; then
        echo "  [skip] $tf_resource already in state"
        return 0
    fi

    # Check if exists in Databricks
    if eval "$check_cmd" &>/dev/null; then
        echo "  [import] $tf_resource"
        terraform import $TF_VARS "$tf_resource" "$db_id" 2>/dev/null || true
    else
        echo "  [none] $tf_resource doesn't exist yet"
    fi
}

# Storage credential
import_if_exists \
    'databricks_storage_credential.unity[0]' \
    "${PREFIX}-adls-credential" \
    "databricks unity-catalog storage-credentials get ${PREFIX}-adls-credential"

# External location
import_if_exists \
    'databricks_external_location.catalog[0]' \
    "${PREFIX}-catalog-location" \
    "databricks unity-catalog external-locations get ${PREFIX}-catalog-location"

# Secret scope
import_if_exists \
    'databricks_secret_scope.oauth[0]' \
    "mcp-agent-oauth" \
    "databricks secrets list-secrets mcp-agent-oauth"

# Service principal (check by display name)
SP_ID=$(databricks service-principals list --output json 2>/dev/null | jq -r ".[] | select(.displayName == \"${PREFIX}-agent-caller\") | .id" || echo "")
if [ -n "$SP_ID" ] && [ "$SP_ID" != "null" ]; then
    if ! terraform state show 'databricks_service_principal.agent_caller[0]' &>/dev/null; then
        echo "  [import] databricks_service_principal.agent_caller[0]"
        terraform import $TF_VARS 'databricks_service_principal.agent_caller[0]' "$SP_ID" 2>/dev/null || true
    else
        echo "  [skip] databricks_service_principal.agent_caller[0] already in state"
    fi
else
    echo "  [none] Service principal doesn't exist yet"
fi

# Catalog
import_if_exists \
    'databricks_catalog.mcp_agents[0]' \
    "mcp_agents" \
    "databricks unity-catalog catalogs get mcp_agents"

# Schema
import_if_exists \
    'databricks_schema.tools[0]' \
    "mcp_agents.tools" \
    "databricks unity-catalog schemas get mcp_agents.tools"

echo "=== Import Complete ==="
