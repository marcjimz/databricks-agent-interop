# Azure APIM A2A Gateway - Main Configuration

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.80"
    }
  }

  # Uncomment to use remote state
  # backend "azurerm" {
  #   resource_group_name  = "rg-terraform-state"
  #   storage_account_name = "tfstatea2agateway"
  #   container_name       = "tfstate"
  #   key                  = "a2a-gateway.tfstate"
  # }
}

provider "azurerm" {
  features {
    api_management {
      purge_soft_delete_on_destroy = true
    }
  }
}

# Resource Group
resource "azurerm_resource_group" "main" {
  name     = "rg-${var.resource_prefix}-gateway-${var.environment}"
  location = var.location
  tags     = local.tags
}

# Local values
locals {
  tags = merge(var.tags, {
    Environment = var.environment
    Project     = "a2a-gateway"
    ManagedBy   = "terraform"
  })

  apim_name = "${var.resource_prefix}-gateway-${var.environment}"

  # Databricks OIDC endpoints
  databricks_oidc_url = "${var.databricks_host}/oidc/.well-known/openid-configuration"
  databricks_issuer   = "${var.databricks_host}/oidc"
}

# Application Insights for logging
resource "azurerm_application_insights" "main" {
  name                = "ai-${local.apim_name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "web"
  tags                = local.tags
}
