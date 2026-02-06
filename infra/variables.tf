# Azure APIM A2A Gateway - Variables

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "eastus2"
}

variable "resource_prefix" {
  description = "Prefix for all resource names"
  type        = string
  default     = "a2a"
}

# Databricks Configuration
variable "databricks_host" {
  description = "Databricks workspace URL (e.g., https://xxx.cloud.databricks.com)"
  type        = string
}

variable "databricks_workspace_id" {
  description = "Databricks workspace ID (for audience validation)"
  type        = string
}

# Entra ID Configuration
variable "entra_tenant_id" {
  description = "Entra ID (Azure AD) tenant ID"
  type        = string
}

# APIM Configuration
variable "apim_sku" {
  description = "APIM SKU (Consumption, Developer, Basic, Standard, Premium)"
  type        = string
  default     = "Consumption"
}

variable "apim_publisher_name" {
  description = "Publisher name for APIM"
  type        = string
  default     = "A2A Gateway"
}

variable "apim_publisher_email" {
  description = "Publisher email for APIM"
  type        = string
}

# Gateway Configuration
variable "gateway_version" {
  description = "Version of the A2A gateway (for tracing)"
  type        = string
  default     = "1.0.0"
}

# Tags
variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
