variable "subscription_id" {
  description = "Azure subscription ID to deploy resources into"
  type        = string
}

variable "prefix" {
  description = "Resource name prefix (should match Databricks PREFIX for consistency)"
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,19}$", var.prefix))
    error_message = "Prefix must start with a letter, contain only lowercase letters, numbers, and hyphens, and be at most 20 characters."
  }
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "eastus"
}

variable "databricks_gateway_url" {
  description = "URL of the Databricks A2A Gateway (e.g., https://prefix-a2a-gateway.databricksapps.com)"
  type        = string

  validation {
    condition     = can(regex("^https://", var.databricks_gateway_url))
    error_message = "Databricks gateway URL must start with https://"
  }
}

variable "tenant_id" {
  description = "Azure Entra ID tenant ID (must be same tenant as Databricks for pass-through auth)"
  type        = string
}

variable "model_deployment_name" {
  description = "Name for the model deployment (e.g., gpt-4o, gpt-4)"
  type        = string
  default     = "gpt-4o"
}

variable "model_name" {
  description = "Azure OpenAI model name to deploy"
  type        = string
  default     = "gpt-4o"
}

variable "model_version" {
  description = "Model version to deploy"
  type        = string
  default     = "2024-08-06"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default = {
    project     = "a2a-gateway"
    environment = "demo"
    managed_by  = "terraform"
  }
}
