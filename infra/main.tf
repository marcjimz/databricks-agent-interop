# =============================================================================
# MCP Agent Interoperability Infrastructure
# =============================================================================
#
# Deploys everything needed for UC-backed MCP agent interoperability:
#   - Azure Databricks Workspace with Unity Catalog
#   - Azure AI Foundry (AI Hub + AI Services)
#   - UC Catalog and Schema for MCP tools
#   - UC Functions that wrap external agents
#   - SQL Warehouse for function execution
#
# Architecture:
#   Foundry Agent <-> Databricks Managed MCP <-> UC Functions <-> External Agents
#
# Deployment Phases:
#   1. make deploy    - Azure infrastructure (Databricks, Foundry, Storage)
#   2. Manual         - Assign metastore in Databricks account console
#   3. make deploy-uc - Unity Catalog resources (catalog, schema, warehouse)
#
# Authentication:
#   Same Entra ID tenant enables seamless OBO token flow
# =============================================================================

terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.0"
    }
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id

  features {
    key_vault {
      purge_soft_delete_on_destroy       = true
      recover_soft_deleted_key_vaults    = false
      purge_soft_deleted_keys_on_destroy = false
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azuread" {}

# =============================================================================
# Variables
# =============================================================================

variable "location" {
  description = "Azure region for all resources"
  default     = "eastus2"
}

variable "prefix" {
  description = "Prefix for resource names"
  default     = "mcp-interop"
}

variable "tenant_id" {
  description = "Entra ID tenant ID (must match your az login)"
}

variable "subscription_id" {
  description = "Azure subscription ID"
}

variable "deploy_uc" {
  description = "Deploy Unity Catalog resources (requires metastore already assigned)"
  default     = false
}

# =============================================================================
# Data Sources
# =============================================================================

data "azurerm_client_config" "current" {}

# =============================================================================
# Resource Group
# =============================================================================

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.prefix}"
  location = var.location

  tags = {
    purpose    = "mcp-agent-interoperability"
    managed_by = "terraform"
  }
}

# =============================================================================
# Azure Databricks Workspace
# =============================================================================

resource "azurerm_databricks_workspace" "main" {
  name                        = "dbx-${var.prefix}"
  resource_group_name         = azurerm_resource_group.main.name
  location                    = azurerm_resource_group.main.location
  sku                         = "premium" # Required for Unity Catalog
  managed_resource_group_name = "rg-${var.prefix}-dbx-managed"

  tags = {
    purpose = "mcp-agent-interoperability"
  }
}

# =============================================================================
# Azure AI Foundry Resources
# =============================================================================

# Key Vault for AI Foundry
resource "azurerm_key_vault" "foundry" {
  name                       = replace("kv${var.prefix}", "-", "")
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = true
  soft_delete_retention_days = 7

  tags = {
    purpose = "ai-foundry"
  }
}

# Key Vault access policy for current user
resource "azurerm_key_vault_access_policy" "current" {
  key_vault_id = azurerm_key_vault.foundry.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  key_permissions = [
    "Create",
    "Get",
    "Delete",
    "Purge",
    "GetRotationPolicy",
  ]

  secret_permissions = [
    "Get",
    "List",
    "Set",
    "Delete",
    "Purge",
  ]
}

# Storage Account for AI Foundry
resource "azurerm_storage_account" "foundry" {
  name                     = replace("st${var.prefix}ai", "-", "")
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  tags = {
    purpose = "ai-foundry"
  }
}

# Azure AI Services
resource "azurerm_ai_services" "main" {
  name                  = "ais-${var.prefix}"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  sku_name              = "S0"
  custom_subdomain_name = replace("ais${var.prefix}", "-", "")

  identity {
    type = "SystemAssigned"
  }

  tags = {
    purpose = "mcp-agent-interoperability"
  }
}

# Azure AI Foundry Hub
resource "azurerm_ai_foundry" "main" {
  name                = "aihub-${var.prefix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  storage_account_id  = azurerm_storage_account.foundry.id
  key_vault_id        = azurerm_key_vault.foundry.id

  identity {
    type = "SystemAssigned"
  }

  tags = {
    purpose = "mcp-agent-interoperability"
  }

  depends_on = [azurerm_key_vault_access_policy.current]
}

# Azure AI Foundry Project
resource "azurerm_ai_foundry_project" "main" {
  name               = "proj-${var.prefix}"
  location           = azurerm_ai_foundry.main.location
  ai_services_hub_id = azurerm_ai_foundry.main.id

  identity {
    type = "SystemAssigned"
  }

  tags = {
    purpose = "mcp-agent-interoperability"
  }
}

# =============================================================================
# Unity Catalog Storage (ADLS Gen2)
# =============================================================================

resource "azurerm_storage_account" "unity" {
  name                     = replace("st${var.prefix}uc", "-", "")
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  is_hns_enabled           = true # Required for ADLS Gen2

  tags = {
    purpose = "unity-catalog-storage"
  }
}

resource "azurerm_storage_container" "catalog" {
  name               = "catalog"
  storage_account_id = azurerm_storage_account.unity.id
}

# Access Connector for Unity Catalog (managed identity)
resource "azurerm_databricks_access_connector" "unity" {
  name                = "ac-${var.prefix}-unity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  identity {
    type = "SystemAssigned"
  }

  tags = {
    purpose = "unity-catalog-access"
  }
}

# Grant Access Connector access to storage
resource "azurerm_role_assignment" "unity_storage" {
  scope                = azurerm_storage_account.unity.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.unity.identity[0].principal_id
}

# =============================================================================
# Databricks Provider (workspace-level)
# =============================================================================

provider "databricks" {
  alias = "workspace"
  host  = "https://${azurerm_databricks_workspace.main.workspace_url}"
}

# =============================================================================
# Unity Catalog Resources (Phase 2 - requires metastore already assigned)
# =============================================================================

# Storage Credential for ADLS access
resource "databricks_storage_credential" "unity" {
  count    = var.deploy_uc ? 1 : 0
  provider = databricks.workspace
  name     = "${var.prefix}-adls-credential"

  azure_managed_identity {
    access_connector_id = azurerm_databricks_access_connector.unity.id
  }
}

# External Location
resource "databricks_external_location" "catalog" {
  count           = var.deploy_uc ? 1 : 0
  provider        = databricks.workspace
  name            = "${var.prefix}-catalog-location"
  url             = "abfss://${azurerm_storage_container.catalog.name}@${azurerm_storage_account.unity.name}.dfs.core.windows.net/"
  credential_name = databricks_storage_credential.unity[0].name

  depends_on = [databricks_storage_credential.unity]
}

# =============================================================================
# Databricks Service Principal for Agent Access (OAuth M2M)
# =============================================================================
# This SP is used by UC HTTP Connections to authenticate with Databricks Apps.
# OAuth secrets are created via the Databricks API for M2M authentication.

# Databricks Service Principal (native, not Azure AD linked)
resource "databricks_service_principal" "agent_caller" {
  count                = var.deploy_uc ? 1 : 0
  provider             = databricks.workspace
  display_name         = "${var.prefix}-agent-caller"
  allow_cluster_create = false
}

# =============================================================================
# Databricks Secret Scope for OAuth Credentials
# =============================================================================
# Note: OAuth secret creation and storage is handled by the create-sp-secret
# script after Terraform apply, as databricks_service_principal_secret has
# limited Azure support.

resource "databricks_secret_scope" "oauth" {
  count    = var.deploy_uc ? 1 : 0
  provider = databricks.workspace
  name     = "mcp-agent-oauth"

  depends_on = [databricks_service_principal.agent_caller]
}

resource "databricks_secret" "client_id" {
  count        = var.deploy_uc ? 1 : 0
  provider     = databricks.workspace
  scope        = databricks_secret_scope.oauth[0].name
  key          = "client-id"
  string_value = databricks_service_principal.agent_caller[0].application_id
}

# Placeholder for client_secret - will be populated by create-sp-secret script
# The actual secret is created via Databricks API and stored separately

# =============================================================================
# MCP Agents Catalog and Schema
# =============================================================================

resource "databricks_catalog" "mcp_agents" {
  count        = var.deploy_uc ? 1 : 0
  provider     = databricks.workspace
  name         = "mcp_agents"
  storage_root = "abfss://${azurerm_storage_container.catalog.name}@${azurerm_storage_account.unity.name}.dfs.core.windows.net/mcp_agents"
  comment      = "Catalog for MCP agent tools - wraps external agents as UC Functions"

  depends_on = [databricks_external_location.catalog]
}

resource "databricks_schema" "tools" {
  count        = var.deploy_uc ? 1 : 0
  provider     = databricks.workspace
  catalog_name = databricks_catalog.mcp_agents[0].name
  name         = "tools"
  comment      = "UC Functions exposed as MCP tools via Databricks managed MCP servers"

  depends_on = [databricks_catalog.mcp_agents]
}

# =============================================================================
# Outputs
# =============================================================================

output "databricks_workspace_url" {
  description = "Databricks workspace URL"
  value       = "https://${azurerm_databricks_workspace.main.workspace_url}"
}

output "databricks_workspace_id" {
  description = "Databricks workspace ID"
  value       = azurerm_databricks_workspace.main.workspace_id
}

output "mcp_endpoint_base" {
  description = "Base MCP endpoint for managed MCP servers"
  value       = "https://${azurerm_databricks_workspace.main.workspace_url}/api/2.0/mcp"
}

output "mcp_functions_endpoint" {
  description = "MCP endpoint for UC Functions (once registered)"
  value       = "https://${azurerm_databricks_workspace.main.workspace_url}/api/2.0/mcp/functions/mcp_agents/tools/{function_name}"
}

output "foundry_endpoint" {
  description = "Azure AI Services endpoint"
  value       = azurerm_ai_services.main.endpoint
}

output "foundry_hub_id" {
  description = "AI Foundry Hub resource ID"
  value       = azurerm_ai_foundry.main.id
}

output "foundry_project_id" {
  description = "AI Foundry Project resource ID"
  value       = azurerm_ai_foundry_project.main.id
}

output "resource_group" {
  description = "Resource group name"
  value       = azurerm_resource_group.main.name
}

output "tenant_id" {
  description = "Entra ID tenant"
  value       = var.tenant_id
}

output "catalog_schema" {
  description = "UC catalog.schema for MCP tools"
  value       = var.deploy_uc ? "mcp_agents.tools" : "(run 'make deploy-uc' after metastore assignment)"
}

output "storage_account_unity" {
  description = "Unity Catalog storage account"
  value       = azurerm_storage_account.unity.name
}

output "access_connector_id" {
  description = "Access Connector ID for UC"
  value       = azurerm_databricks_access_connector.unity.id
}

# OAuth M2M credentials for UC HTTP Connections
output "oauth_client_id" {
  description = "OAuth client ID (SP application ID) for M2M authentication"
  value       = var.deploy_uc ? databricks_service_principal.agent_caller[0].application_id : null
  sensitive   = true
}

output "oauth_token_endpoint" {
  description = "OAuth token endpoint for M2M authentication"
  value       = "https://${azurerm_databricks_workspace.main.workspace_url}/oidc/v1/token"
}

output "oauth_secret_scope" {
  description = "Databricks secret scope containing OAuth credentials"
  value       = var.deploy_uc ? databricks_secret_scope.oauth[0].name : null
}

output "service_principal_id" {
  description = "Service Principal ID for granting app permissions"
  value       = var.deploy_uc ? databricks_service_principal.agent_caller[0].id : null
}

output "service_principal_name" {
  description = "Service Principal display name"
  value       = var.deploy_uc ? databricks_service_principal.agent_caller[0].display_name : null
}

# Instructions for next steps
output "next_steps" {
  description = "Next steps after deployment"
  value       = var.deploy_uc ? "Ready! Grant SP permission on app: databricks apps set-permission calculator-agent --permission CAN_USE --service-principal-name ${var.prefix}-agent-caller" : "1. Assign metastore in Databricks account console  2. Run 'make deploy-uc'"
}
