# Outputs

output "apim_gateway_url" {
  description = "APIM gateway URL"
  value       = azurerm_api_management.main.gateway_url
}

output "apim_management_url" {
  description = "APIM management API URL"
  value       = azurerm_api_management.main.management_api_url
}

output "apim_portal_url" {
  description = "APIM developer portal URL"
  value       = azurerm_api_management.main.developer_portal_url
}

output "a2a_gateway_base_url" {
  description = "A2A Gateway base URL"
  value       = "${azurerm_api_management.main.gateway_url}/a2a"
}

output "resource_group_name" {
  description = "Resource group name"
  value       = azurerm_resource_group.main.name
}

output "application_insights_connection_string" {
  description = "Application Insights connection string"
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}
