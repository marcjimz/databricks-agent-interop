# -----------------------------------------------------------------------------
# A2A Connection to Databricks Gateway
#
# This creates an A2A connection in the AI Foundry project that points to
# the Databricks A2A Gateway. This allows AI Foundry agents to call
# Databricks agents via the A2A protocol.
#
# Authentication uses ProjectManagedIdentity since both Azure and Databricks
# are in the same Entra ID tenant. The token audience is set to the Databricks
# API to enable authentication.
# -----------------------------------------------------------------------------

# Databricks API audience for same-tenant authentication
locals {
  databricks_api_audience = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
}

# A2A Connection to Databricks Gateway using ProjectManagedIdentity
# This enables AI Foundry agents to call Databricks agents
resource "azapi_resource" "databricks_a2a_connection" {
  type      = "Microsoft.MachineLearningServices/workspaces/connections@2025-04-01-preview"
  name      = "databricks-a2a-gateway"
  parent_id = azurerm_ai_foundry_project.demo.id

  body = jsonencode({
    properties = {
      authType       = "ProjectManagedIdentity"
      group          = "ServicesAndApps"
      category       = "RemoteA2A"
      target         = var.databricks_gateway_url
      isSharedToAll  = true
      sharedUserList = []
      audience       = local.databricks_api_audience
      Credentials    = {}
      metadata = {
        ApiType     = "Azure"
        Description = "A2A connection to Databricks Gateway for agent interoperability"
      }
    }
  })

  depends_on = [
    azurerm_ai_foundry_project.demo,
    azapi_resource.ai_services_connection
  ]
}

# -----------------------------------------------------------------------------
# Alternative: A2A Connection with Custom OAuth (for cross-tenant scenarios)
#
# Uncomment this block if you need to connect to a Databricks gateway in a
# different Entra ID tenant. You'll need to provide OAuth credentials.
# -----------------------------------------------------------------------------

# variable "databricks_client_id" {
#   description = "OAuth client ID for cross-tenant Databricks access"
#   type        = string
#   default     = ""
#   sensitive   = true
# }
#
# variable "databricks_client_secret" {
#   description = "OAuth client secret for cross-tenant Databricks access"
#   type        = string
#   default     = ""
#   sensitive   = true
# }
#
# resource "azapi_resource" "databricks_a2a_connection_oauth" {
#   count     = var.databricks_client_id != "" ? 1 : 0
#   type      = "Microsoft.MachineLearningServices/workspaces/connections@2025-04-01-preview"
#   name      = "databricks-a2a-gateway-oauth"
#   parent_id = azurerm_ai_foundry_project.demo.id
#
#   body = jsonencode({
#     properties = {
#       authType       = "OAuth2"
#       group          = "ServicesAndApps"
#       category       = "RemoteA2A"
#       target         = var.databricks_gateway_url
#       isSharedToAll  = true
#       sharedUserList = []
#       TokenUrl       = "https://login.microsoftonline.com/${var.tenant_id}/oauth2/v2.0/token"
#       Scopes         = ["${local.databricks_api_audience}/.default"]
#       Credentials = {
#         ClientId     = var.databricks_client_id
#         ClientSecret = var.databricks_client_secret
#       }
#       metadata = {
#         ApiType     = "Azure"
#         Description = "A2A connection to Databricks Gateway (cross-tenant OAuth)"
#       }
#     }
#   })
# }
