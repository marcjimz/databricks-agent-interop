# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.a2a.name
}

output "resource_group_id" {
  description = "ID of the resource group"
  value       = azurerm_resource_group.a2a.id
}

# -----------------------------------------------------------------------------
# AI Foundry Outputs
# -----------------------------------------------------------------------------

output "ai_foundry_hub_name" {
  description = "Name of the AI Foundry Hub"
  value       = azurerm_ai_foundry.hub.name
}

output "ai_foundry_hub_id" {
  description = "ID of the AI Foundry Hub"
  value       = azurerm_ai_foundry.hub.id
}

output "ai_foundry_project_name" {
  description = "Name of the AI Foundry Project"
  value       = azurerm_ai_foundry_project.demo.name
}

output "ai_foundry_project_id" {
  description = "ID of the AI Foundry Project"
  value       = azurerm_ai_foundry_project.demo.id
}

output "ai_foundry_project_endpoint" {
  description = "Endpoint URL for the AI Foundry Project (use for SDK)"
  value       = "https://${azurerm_resource_group.a2a.location}.api.azureml.ms/rp/workspaces/${azurerm_ai_foundry_project.demo.id}"
}

output "ai_foundry_portal_url" {
  description = "URL to access AI Foundry in Azure Portal"
  value       = "https://ai.azure.com/build/overview?wsid=${azurerm_ai_foundry_project.demo.id}"
}

# -----------------------------------------------------------------------------
# AI Services Outputs
# -----------------------------------------------------------------------------

output "ai_services_name" {
  description = "Name of the AI Services resource"
  value       = azurerm_ai_services.a2a.name
}

output "ai_services_endpoint" {
  description = "Endpoint URL for AI Services"
  value       = azurerm_ai_services.a2a.endpoint
}

output "model_deployment_name" {
  description = "Name of the deployed model"
  value       = azurerm_cognitive_deployment.gpt4o.name
}

# -----------------------------------------------------------------------------
# A2A Connection Outputs
# -----------------------------------------------------------------------------

output "a2a_connection_id" {
  description = "ID of the A2A connection to Databricks Gateway"
  value       = azapi_resource.databricks_a2a_connection.id
}

output "a2a_connection_name" {
  description = "Name of the A2A connection"
  value       = azapi_resource.databricks_a2a_connection.name
}

output "databricks_gateway_url" {
  description = "URL of the Databricks A2A Gateway (configured target)"
  value       = var.databricks_gateway_url
}

# -----------------------------------------------------------------------------
# Identity Outputs
# -----------------------------------------------------------------------------

output "ai_foundry_hub_principal_id" {
  description = "Principal ID of the AI Foundry Hub managed identity"
  value       = azurerm_ai_foundry.hub.identity[0].principal_id
}

output "ai_foundry_project_principal_id" {
  description = "Principal ID of the AI Foundry Project managed identity"
  value       = azurerm_ai_foundry_project.demo.identity[0].principal_id
}

# -----------------------------------------------------------------------------
# Configuration Outputs (for scripts)
# -----------------------------------------------------------------------------

output "environment_variables" {
  description = "Environment variables for SDK usage"
  value = {
    FOUNDRY_PROJECT_ENDPOINT      = "https://${azurerm_resource_group.a2a.location}.api.azureml.ms/rp/workspaces/${azurerm_ai_foundry_project.demo.id}"
    FOUNDRY_MODEL_DEPLOYMENT_NAME = azurerm_cognitive_deployment.gpt4o.name
    A2A_PROJECT_CONNECTION_NAME   = azapi_resource.databricks_a2a_connection.name
    A2A_PROJECT_CONNECTION_ID     = azapi_resource.databricks_a2a_connection.id
  }
  sensitive = false
}
