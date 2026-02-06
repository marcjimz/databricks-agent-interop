# A2A Gateway API Definition

resource "azurerm_api_management_api" "a2a" {
  name                  = "a2a-gateway"
  api_management_name   = azurerm_api_management.main.name
  resource_group_name   = azurerm_resource_group.main.name
  revision              = "1"
  display_name          = "A2A Gateway"
  path                  = "a2a"
  protocols             = ["https"]
  subscription_required = false

  description = "Agent-to-Agent Gateway with Unity Catalog authorization"
}

# API Policy (applies to all operations)
resource "azurerm_api_management_api_policy" "a2a" {
  api_name            = azurerm_api_management_api.a2a.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name

  xml_content = file("${path.module}/../apim/policies/api-policy.xml")
}

# Operation: List Agents
resource "azurerm_api_management_api_operation" "list_agents" {
  operation_id        = "list-agents"
  api_name            = azurerm_api_management_api.a2a.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "List Agents"
  method              = "GET"
  url_template        = "/agents"

  response {
    status_code = 200
    description = "List of accessible agents"
  }

  response {
    status_code = 401
    description = "Unauthorized"
  }
}

resource "azurerm_api_management_api_operation_policy" "list_agents" {
  api_name            = azurerm_api_management_api_operation.list_agents.api_name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  operation_id        = azurerm_api_management_api_operation.list_agents.operation_id

  xml_content = file("${path.module}/../apim/policies/agents-list.xml")
}

# Operation: Get Agent
resource "azurerm_api_management_api_operation" "get_agent" {
  operation_id        = "get-agent"
  api_name            = azurerm_api_management_api.a2a.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "Get Agent"
  method              = "GET"
  url_template        = "/agents/{name}"

  template_parameter {
    name     = "name"
    type     = "string"
    required = true
  }

  response {
    status_code = 200
    description = "Agent info"
  }

  response {
    status_code = 403
    description = "Access denied"
  }

  response {
    status_code = 404
    description = "Agent not found"
  }
}

resource "azurerm_api_management_api_operation_policy" "get_agent" {
  api_name            = azurerm_api_management_api_operation.get_agent.api_name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  operation_id        = azurerm_api_management_api_operation.get_agent.operation_id

  xml_content = file("${path.module}/../apim/policies/agent-get.xml")
}

# Operation: Get Agent Card
resource "azurerm_api_management_api_operation" "get_agent_card" {
  operation_id        = "get-agent-card"
  api_name            = azurerm_api_management_api.a2a.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "Get Agent Card"
  method              = "GET"
  url_template        = "/agents/{name}/.well-known/agent.json"

  template_parameter {
    name     = "name"
    type     = "string"
    required = true
  }

  response {
    status_code = 200
    description = "A2A Agent card"
  }
}

resource "azurerm_api_management_api_operation_policy" "get_agent_card" {
  api_name            = azurerm_api_management_api_operation.get_agent_card.api_name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  operation_id        = azurerm_api_management_api_operation.get_agent_card.operation_id

  xml_content = file("${path.module}/../apim/policies/agent-card.xml")
}

# Operation: Send Message (JSON-RPC)
resource "azurerm_api_management_api_operation" "send_message" {
  operation_id        = "send-message"
  api_name            = azurerm_api_management_api.a2a.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "Send Message"
  method              = "POST"
  url_template        = "/agents/{name}"

  template_parameter {
    name     = "name"
    type     = "string"
    required = true
  }

  response {
    status_code = 200
    description = "JSON-RPC response"
  }
}

resource "azurerm_api_management_api_operation_policy" "send_message" {
  api_name            = azurerm_api_management_api_operation.send_message.api_name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  operation_id        = azurerm_api_management_api_operation.send_message.operation_id

  xml_content = file("${path.module}/../apim/policies/agent-rpc.xml")
}

# Operation: Stream Message (SSE)
resource "azurerm_api_management_api_operation" "stream_message" {
  operation_id        = "stream-message"
  api_name            = azurerm_api_management_api.a2a.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "Stream Message"
  method              = "POST"
  url_template        = "/agents/{name}/stream"

  template_parameter {
    name     = "name"
    type     = "string"
    required = true
  }

  response {
    status_code = 200
    description = "SSE stream"
  }
}

resource "azurerm_api_management_api_operation_policy" "stream_message" {
  api_name            = azurerm_api_management_api_operation.stream_message.api_name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  operation_id        = azurerm_api_management_api_operation.stream_message.operation_id

  xml_content = file("${path.module}/../apim/policies/agent-stream.xml")
}
