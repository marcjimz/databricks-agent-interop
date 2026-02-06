# Azure API Management Instance

resource "azurerm_api_management" "main" {
  name                = "apim-${local.apim_name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  publisher_name  = var.apim_publisher_name
  publisher_email = var.apim_publisher_email

  sku_name = "${var.apim_sku}_0"

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

# Application Insights Logger
resource "azurerm_api_management_logger" "main" {
  name                = "ai-logger"
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name

  application_insights {
    instrumentation_key = azurerm_application_insights.main.instrumentation_key
  }
}

# Named Values (Configuration)
resource "azurerm_api_management_named_value" "databricks_host" {
  name                = "databricks-host"
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "databricks-host"
  value               = var.databricks_host
}

# Note: OIDC-related named values removed - using validate-azure-ad-token
# which handles Entra ID OAuth validation automatically without OIDC discovery

resource "azurerm_api_management_named_value" "entra_tenant_id" {
  name                = "entra-tenant-id"
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "entra-tenant-id"
  value               = var.entra_tenant_id
}

resource "azurerm_api_management_named_value" "a2a_connection_suffix" {
  name                = "a2a-connection-suffix"
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "a2a-connection-suffix"
  value               = "-a2a"
}

resource "azurerm_api_management_named_value" "gateway_version" {
  name                = "gateway-version"
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "gateway-version"
  value               = var.gateway_version
}

resource "azurerm_api_management_named_value" "gateway_environment" {
  name                = "gateway-environment"
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "gateway-environment"
  value               = var.environment
}

# Global Policy
resource "azurerm_api_management_policy" "global" {
  api_management_id = azurerm_api_management.main.id

  xml_content = <<XML
<policies>
    <inbound>
        <cors allow-credentials="true">
            <allowed-origins>
                <origin>*</origin>
            </allowed-origins>
            <allowed-methods>
                <method>*</method>
            </allowed-methods>
            <allowed-headers>
                <header>*</header>
            </allowed-headers>
        </cors>
    </inbound>
    <backend>
        <forward-request />
    </backend>
    <outbound />
    <on-error>
        <set-header name="Content-Type" exists-action="override">
            <value>application/json</value>
        </set-header>
        <set-body>@{
            return new JObject(
                new JProperty("error", context.LastError.Source),
                new JProperty("message", context.LastError.Message),
                new JProperty("reason", context.LastError.Reason)
            ).ToString();
        }</set-body>
    </on-error>
</policies>
XML
}
