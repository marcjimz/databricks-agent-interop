# -----------------------------------------------------------------------------
# Azure AI Foundry Infrastructure for A2A Gateway Integration
#
# This configuration deploys:
# - Resource Group
# - Key Vault (for secrets)
# - Storage Account (for AI Foundry data)
# - AI Services (Azure OpenAI models)
# - AI Foundry Hub
# - AI Foundry Project
# -----------------------------------------------------------------------------

# Get current Azure client configuration
data "azurerm_client_config" "current" {}

# Generate unique suffix for globally unique resource names
resource "random_string" "suffix" {
  length  = 6
  lower   = true
  numeric = true
  special = false
  upper   = false
}

locals {
  # Sanitized prefix for resources that don't allow hyphens
  prefix_clean = replace(var.prefix, "-", "")
  suffix       = random_string.suffix.result
}

# -----------------------------------------------------------------------------
# Resource Group
# -----------------------------------------------------------------------------

resource "azurerm_resource_group" "a2a" {
  name     = "${var.prefix}-a2a-foundry-rg"
  location = var.location
  tags     = var.tags
}

# -----------------------------------------------------------------------------
# Key Vault
# -----------------------------------------------------------------------------

resource "azurerm_key_vault" "a2a" {
  name                       = "${local.prefix_clean}a2akv${local.suffix}"
  location                   = azurerm_resource_group.a2a.location
  resource_group_name        = azurerm_resource_group.a2a.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = false
  soft_delete_retention_days = 7

  tags = var.tags
}

# Key Vault access policy for current user (deployer)
resource "azurerm_key_vault_access_policy" "deployer" {
  key_vault_id = azurerm_key_vault.a2a.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  key_permissions = [
    "Create",
    "Get",
    "Delete",
    "Purge",
    "GetRotationPolicy",
    "List",
  ]

  secret_permissions = [
    "Get",
    "Set",
    "Delete",
    "Purge",
    "List",
  ]
}

# -----------------------------------------------------------------------------
# Storage Account
# -----------------------------------------------------------------------------

resource "azurerm_storage_account" "a2a" {
  name                     = "${local.prefix_clean}a2ast${local.suffix}"
  location                 = azurerm_resource_group.a2a.location
  resource_group_name      = azurerm_resource_group.a2a.name
  account_tier             = "Standard"
  account_replication_type = "LRS"

  # Required for AI Foundry
  allow_nested_items_to_be_public = false

  tags = var.tags
}

# -----------------------------------------------------------------------------
# AI Services (Azure OpenAI)
# -----------------------------------------------------------------------------

resource "azurerm_ai_services" "a2a" {
  name                  = "${var.prefix}-a2a-ai-services"
  location              = azurerm_resource_group.a2a.location
  resource_group_name   = azurerm_resource_group.a2a.name
  sku_name              = "S0"
  custom_subdomain_name = "${local.prefix_clean}a2aai${local.suffix}"

  tags = var.tags
}

# Deploy GPT-4o model
resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = var.model_deployment_name
  cognitive_account_id = azurerm_ai_services.a2a.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "Standard"
    capacity = 10
  }
}

# -----------------------------------------------------------------------------
# AI Foundry Hub
# -----------------------------------------------------------------------------

resource "azurerm_ai_foundry" "hub" {
  name                = "${var.prefix}-a2a-hub"
  location            = azurerm_resource_group.a2a.location
  resource_group_name = azurerm_resource_group.a2a.name
  storage_account_id  = azurerm_storage_account.a2a.id
  key_vault_id        = azurerm_key_vault.a2a.id

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags

  depends_on = [
    azurerm_key_vault_access_policy.deployer
  ]
}

# Grant AI Foundry Hub access to Key Vault
resource "azurerm_key_vault_access_policy" "hub" {
  key_vault_id = azurerm_key_vault.a2a.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_ai_foundry.hub.identity[0].principal_id

  key_permissions = [
    "Get",
    "List",
    "Create",
  ]

  secret_permissions = [
    "Get",
    "Set",
    "List",
  ]
}

# -----------------------------------------------------------------------------
# AI Foundry Project
# -----------------------------------------------------------------------------

resource "azurerm_ai_foundry_project" "demo" {
  name               = "${var.prefix}-a2a-project"
  location           = azurerm_ai_foundry.hub.location
  ai_services_hub_id = azurerm_ai_foundry.hub.id

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

# Grant AI Foundry Project access to Key Vault
resource "azurerm_key_vault_access_policy" "project" {
  key_vault_id = azurerm_key_vault.a2a.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_ai_foundry_project.demo.identity[0].principal_id

  key_permissions = [
    "Get",
    "List",
  ]

  secret_permissions = [
    "Get",
    "List",
  ]
}

# Connect AI Services to AI Foundry Hub
resource "azapi_resource" "ai_services_connection" {
  type      = "Microsoft.MachineLearningServices/workspaces/connections@2024-04-01"
  name      = "ai-services-connection"
  parent_id = azurerm_ai_foundry.hub.id

  body = jsonencode({
    properties = {
      category      = "AzureOpenAI"
      target        = azurerm_ai_services.a2a.endpoint
      authType      = "AAD"
      isSharedToAll = true
      metadata = {
        ApiType    = "Azure"
        ResourceId = azurerm_ai_services.a2a.id
      }
    }
  })

  depends_on = [
    azurerm_ai_foundry_project.demo
  ]
}
