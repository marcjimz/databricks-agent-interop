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
#   Foundry Agent ←→ Databricks Managed MCP ←→ UC Functions ←→ External Agents
#
# Authentication:
#   Same Entra ID tenant enables seamless OBO token flow
# =============================================================================

terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
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
  features {
    key_vault {
      purge_soft_delete_on_destroy = true
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

variable "databricks_account_id" {
  description = "Databricks account ID (from accounts.azuredatabricks.net)"
  default     = ""
}

variable "metastore_id" {
  description = "Existing Unity Catalog metastore ID (leave empty to skip assignment)"
  default     = ""
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

# Azure AI Services (for Foundry)
resource "azurerm_cognitive_account" "foundry" {
  name                  = "ai-${var.prefix}"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  kind                  = "AIServices"
  sku_name              = "S0"
  custom_subdomain_name = replace("ai-${var.prefix}", "-", "")

  identity {
    type = "SystemAssigned"
  }

  tags = {
    purpose = "mcp-agent-interoperability"
  }
}

# Key Vault for secrets
resource "azurerm_key_vault" "main" {
  name                       = replace("kv${var.prefix}", "-", "")
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = false
  soft_delete_retention_days = 7

  access_policy {
    tenant_id = var.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = ["Get", "List", "Set", "Delete", "Purge"]
    key_permissions    = ["Get", "List", "Create", "Delete", "Purge"]
  }
}

# Application Insights
resource "azurerm_application_insights" "main" {
  name                = "appi-${var.prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  application_type    = "web"
}

# Storage for Foundry
resource "azurerm_storage_account" "foundry" {
  name                     = replace("st${var.prefix}ai", "-", "")
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

# AI Hub for Foundry Agents
resource "azurerm_machine_learning_workspace" "hub" {
  name                    = "aihub-${var.prefix}"
  resource_group_name     = azurerm_resource_group.main.name
  location                = azurerm_resource_group.main.location
  kind                    = "Hub"
  application_insights_id = azurerm_application_insights.main.id
  key_vault_id            = azurerm_key_vault.main.id
  storage_account_id      = azurerm_storage_account.foundry.id

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
  name                  = "catalog"
  storage_account_name  = azurerm_storage_account.unity.name
  container_access_type = "private"
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
# Databricks Providers
# =============================================================================

provider "databricks" {
  alias      = "account"
  host       = "https://accounts.azuredatabricks.net"
  account_id = var.databricks_account_id
}

provider "databricks" {
  alias = "workspace"
  host  = "https://${azurerm_databricks_workspace.main.workspace_url}"
}

# =============================================================================
# Unity Catalog Setup
# =============================================================================

# Metastore Assignment (if metastore_id provided)
resource "databricks_metastore_assignment" "main" {
  count        = var.metastore_id != "" && var.databricks_account_id != "" ? 1 : 0
  provider     = databricks.account
  metastore_id = var.metastore_id
  workspace_id = azurerm_databricks_workspace.main.workspace_id
}

# Storage Credential for ADLS access
resource "databricks_storage_credential" "unity" {
  count    = var.metastore_id != "" ? 1 : 0
  provider = databricks.workspace
  name     = "${var.prefix}-adls-credential"

  azure_managed_identity {
    access_connector_id = azurerm_databricks_access_connector.unity.id
  }

  depends_on = [databricks_metastore_assignment.main]
}

# External Location
resource "databricks_external_location" "catalog" {
  count           = var.metastore_id != "" ? 1 : 0
  provider        = databricks.workspace
  name            = "${var.prefix}-catalog-location"
  url             = "abfss://${azurerm_storage_container.catalog.name}@${azurerm_storage_account.unity.name}.dfs.core.windows.net/"
  credential_name = databricks_storage_credential.unity[0].name

  depends_on = [databricks_storage_credential.unity]
}

# =============================================================================
# MCP Agents Catalog and Schema
# =============================================================================

resource "databricks_catalog" "mcp_agents" {
  count        = var.metastore_id != "" ? 1 : 0
  provider     = databricks.workspace
  name         = "mcp_agents"
  storage_root = "abfss://${azurerm_storage_container.catalog.name}@${azurerm_storage_account.unity.name}.dfs.core.windows.net/mcp_agents"
  comment      = "Catalog for MCP agent tools - wraps external agents as UC Functions"

  depends_on = [databricks_external_location.catalog]
}

resource "databricks_schema" "tools" {
  count        = var.metastore_id != "" ? 1 : 0
  provider     = databricks.workspace
  catalog_name = databricks_catalog.mcp_agents[0].name
  name         = "tools"
  comment      = "UC Functions exposed as MCP tools via Databricks managed MCP servers"

  depends_on = [databricks_catalog.mcp_agents]
}

# =============================================================================
# SQL Warehouse for Function Execution
# =============================================================================

resource "databricks_sql_endpoint" "mcp" {
  count            = var.metastore_id != "" ? 1 : 0
  provider         = databricks.workspace
  name             = "mcp-functions"
  cluster_size     = "2X-Small"
  max_num_clusters = 1
  auto_stop_mins   = 10
  warehouse_type   = "PRO"

  tags {
    custom_tags {
      key   = "purpose"
      value = "mcp-function-execution"
    }
  }

  depends_on = [databricks_metastore_assignment.main]
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
  description = "Azure AI Foundry endpoint"
  value       = azurerm_cognitive_account.foundry.endpoint
}

output "ai_hub_id" {
  description = "AI Hub resource ID for Foundry agents"
  value       = azurerm_machine_learning_workspace.hub.id
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
  value       = var.metastore_id != "" ? "mcp_agents.tools" : "(requires metastore assignment)"
}

output "sql_warehouse_id" {
  description = "SQL Warehouse ID for function execution"
  value       = var.metastore_id != "" ? databricks_sql_endpoint.mcp[0].id : "(requires metastore)"
}

output "storage_account_unity" {
  description = "Unity Catalog storage account"
  value       = azurerm_storage_account.unity.name
}

output "access_connector_id" {
  description = "Access Connector ID for UC"
  value       = azurerm_databricks_access_connector.unity.id
}
