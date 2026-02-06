# Configuration Loading from YAML
# Reads gateway.yaml and environment-specific overrides

locals {
  # Load base configuration
  base_config = yamldecode(file("${path.module}/../config/gateway.yaml"))

  # Load environment-specific overrides (if exists)
  env_config_path = "${path.module}/../config/environments/${var.environment}.yaml"
  env_config_exists = fileexists(local.env_config_path)
  env_config = local.env_config_exists ? yamldecode(file(local.env_config_path)) : {}

  # Deep merge base and environment configs
  # Note: Terraform's merge is shallow, so we merge each section
  config = {
    gateway = merge(
      lookup(local.base_config, "gateway", {}),
      lookup(local.env_config, "gateway", {})
    )
    databricks = merge(
      lookup(local.base_config, "databricks", {}),
      lookup(local.env_config, "databricks", {})
    )
    entra = merge(
      lookup(local.base_config, "entra", {}),
      lookup(local.env_config, "entra", {})
    )
    azure = merge(
      lookup(local.base_config, "azure", {}),
      lookup(local.env_config, "azure", {})
    )
    apim = merge(
      lookup(local.base_config, "apim", {}),
      lookup(local.env_config, "apim", {})
    )
    tracing = merge(
      lookup(local.base_config, "tracing", {}),
      lookup(local.env_config, "tracing", {})
    )
  }

  # Resolved configuration values (with variable overrides taking precedence)
  # This allows CLI/environment variable overrides of YAML config
  resolved = {
    gateway_version    = coalesce(var.gateway_version, lookup(local.config.gateway, "version", "1.0.0"))
    environment        = var.environment

    databricks_host         = var.databricks_host
    databricks_workspace_id = var.databricks_workspace_id
    databricks_oidc_url     = "${var.databricks_host}/oidc/.well-known/openid-configuration"
    databricks_issuer       = "${var.databricks_host}/oidc"
    connection_suffix       = lookup(local.config.databricks, "connection_suffix", "-a2a")

    entra_tenant_id = var.entra_tenant_id

    azure_location    = coalesce(var.location, lookup(local.config.azure, "location", "eastus2"))
    resource_prefix   = coalesce(var.resource_prefix, lookup(local.config.azure, "resource_prefix", "a2a"))

    apim_sku             = coalesce(var.apim_sku, lookup(local.config.apim, "sku", "Consumption"))
    apim_publisher_name  = coalesce(var.apim_publisher_name, lookup(local.config.apim, "publisher_name", "A2A Gateway"))
    apim_publisher_email = var.apim_publisher_email

    tracing_enabled = lookup(local.config.tracing, "enabled", true)
    tracing_level   = lookup(local.config.tracing, "log_level", "information")
  }
}

# Output resolved configuration for debugging
output "resolved_config" {
  description = "Resolved configuration values"
  value = {
    environment        = local.resolved.environment
    gateway_version    = local.resolved.gateway_version
    databricks_host    = local.resolved.databricks_host
    apim_sku           = local.resolved.apim_sku
    resource_prefix    = local.resolved.resource_prefix
    tracing_enabled    = local.resolved.tracing_enabled
  }
}
