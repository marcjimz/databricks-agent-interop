# =============================================================================
# MCP Agent Interoperability Infrastructure
# =============================================================================

# Load environment variables from parent .env
ifneq (,$(wildcard ../.env))
    include ../.env
    export
endif

# Defaults
PREFIX ?= mcp-interop
LOCATION ?= eastus2
RESOURCE_GROUP ?= rg-agent-interop

.PHONY: deploy deploy-with-uc destroy test-mcp test-uc-functions outputs help

help:
	@echo "MCP Agent Interoperability Infrastructure"
	@echo ""
	@echo "Usage:"
	@echo "  make deploy              Deploy Azure resources (Databricks + Foundry)"
	@echo "  make deploy-with-uc      Deploy with Unity Catalog metastore assignment"
	@echo "  make destroy             Destroy all resources"
	@echo "  make test-mcp            Test MCP endpoint"
	@echo "  make outputs             Show Terraform outputs"
	@echo ""
	@echo "Configuration (from ../.env):"
	@echo "  TENANT_ID=$(TENANT_ID)"
	@echo "  SUBSCRIPTION_ID=$(SUBSCRIPTION_ID)"
	@echo "  LOCATION=$(LOCATION)"
	@echo "  PREFIX=$(PREFIX)"

check-env:
	@if [ -z "$(TENANT_ID)" ]; then \
		echo "Error: TENANT_ID not set. Run 'make setup' in parent directory and edit .env"; \
		exit 1; \
	fi

# Deploy without metastore (assign manually later)
deploy: check-env
	terraform init
	terraform apply \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)"

# Deploy with auto metastore assignment
deploy-with-uc: check-env
	@if [ -z "$(DATABRICKS_ACCOUNT_ID)" ]; then echo "Error: Set DATABRICKS_ACCOUNT_ID in .env"; exit 1; fi
	@if [ -z "$(UC_METASTORE_ID)" ]; then echo "Error: Set UC_METASTORE_ID in .env"; exit 1; fi
	terraform init
	terraform apply \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)" \
		-var="databricks_account_id=$(DATABRICKS_ACCOUNT_ID)" \
		-var="metastore_id=$(UC_METASTORE_ID)"

destroy: check-env
	terraform destroy \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)"

# Test MCP endpoint (echo function)
test-mcp:
	@echo "=== Testing MCP Endpoint ===" && \
	WORKSPACE_URL=$$(terraform output -raw databricks_workspace_url 2>/dev/null || echo "$(DATABRICKS_HOST)") && \
	TOKEN=$$(az account get-access-token --resource 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d -o tsv --query accessToken) && \
	echo "Workspace: $$WORKSPACE_URL" && \
	echo "" && \
	echo "=== Calling echo function ===" && \
	curl -s -X POST "$$WORKSPACE_URL/api/2.0/mcp/functions/$(UC_CATALOG)/$(UC_SCHEMA)/echo" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"echo","arguments":{"message":"Hello from MCP!"}}}' | python3 -m json.tool

# Test UC Functions MCP endpoint
test-uc-functions:
	@echo "=== Listing UC Functions via MCP ===" && \
	WORKSPACE_URL=$$(terraform output -raw databricks_workspace_url 2>/dev/null || echo "$(DATABRICKS_HOST)") && \
	TOKEN=$$(az account get-access-token --resource 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d -o tsv --query accessToken) && \
	curl -s -X POST "$$WORKSPACE_URL/api/2.0/mcp/functions/$(UC_CATALOG)/$(UC_SCHEMA)" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '{"jsonrpc":"2.0","id":"1","method":"tools/list"}' | python3 -m json.tool

# Show all outputs
outputs:
	@terraform output
