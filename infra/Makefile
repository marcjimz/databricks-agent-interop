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

.PHONY: check-deps check-env deploy deploy-uc create-sp-secret destroy outputs update-env help

help:
	@echo "MCP Agent Interoperability Infrastructure"
	@echo ""
	@echo "Usage:"
	@echo "  make deploy       Deploy Azure infrastructure (Databricks + Foundry)"
	@echo "  make deploy-uc    Deploy Unity Catalog resources (after metastore assignment)"
	@echo "  make destroy      Destroy all resources"
	@echo "  make outputs      Show Terraform outputs"
	@echo ""
	@echo "Deployment Flow:"
	@echo "  1. make deploy    - Deploy Azure resources"
	@echo "  2. Assign metastore in Databricks account console"
	@echo "  3. make deploy-uc - Deploy UC catalog, schema, warehouse"
	@echo ""
	@echo "Configuration (from ../.env):"
	@echo "  TENANT_ID=$(TENANT_ID)"
	@echo "  SUBSCRIPTION_ID=$(SUBSCRIPTION_ID)"
	@echo "  LOCATION=$(LOCATION)"
	@echo "  PREFIX=$(PREFIX)"

check-deps:
	@command -v terraform >/dev/null 2>&1 || { echo "Error: terraform is not installed. Install from https://terraform.io/downloads"; exit 1; }
	@command -v az >/dev/null 2>&1 || { echo "Error: Azure CLI (az) is not installed. Install from https://aka.ms/installazurecli"; exit 1; }

check-env: check-deps
	@if [ -z "$(TENANT_ID)" ]; then \
		echo "Error: TENANT_ID not set. Run 'make setup' in parent directory and edit .env"; \
		exit 1; \
	fi
	@if [ -z "$(SUBSCRIPTION_ID)" ]; then \
		echo "Error: SUBSCRIPTION_ID not set. Run 'make setup' in parent directory and edit .env"; \
		exit 1; \
	fi

# Phase 1: Deploy Azure infrastructure (Databricks workspace, AI Foundry, storage)
deploy: check-env
	terraform init
	terraform apply -auto-approve \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)" \
		-var="deploy_uc=false"
	@$(MAKE) update-env
	@echo ""
	@echo "=== Next Steps ==="
	@echo "1. Go to https://accounts.azuredatabricks.net"
	@echo "2. Assign a metastore to workspace: $$(terraform output -raw databricks_workspace_url)"
	@echo "3. Run: make deploy-uc"

# Phase 2: Deploy Unity Catalog resources (after metastore assignment)
deploy-uc: check-env
	terraform init
	terraform apply -auto-approve \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)" \
		-var="deploy_uc=true"
	@echo ""
	@echo "=== Creating OAuth Secret for Service Principal ==="
	@$(MAKE) create-sp-secret || echo "Note: SP secret creation requires manual step. See docs."
	@echo ""
	@echo "=== Unity Catalog Setup Complete ==="
	@echo "Catalog: mcp_agents"
	@echo "Schema:  mcp_agents.tools"
	@echo "Service Principal: $(PREFIX)-agent-caller"
	@echo "Secret Scope: mcp-agent-oauth"
	@echo ""
	@echo "Next: Run 'cd .. && make deploy-bundle' to deploy apps and register UC functions"

# Create OAuth secret for the service principal
create-sp-secret:
	@echo "Creating OAuth secret for service principal..."
	@./create-sp-secret.sh

destroy: check-env
	terraform destroy -auto-approve \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)" \
		-var="deploy_uc=true"

# Show all outputs
outputs:
	@terraform output

# Update parent .env with Terraform outputs
update-env:
	@echo "Updating ../.env with Terraform outputs..."
	@WORKSPACE_URL=$$(terraform output -raw databricks_workspace_url 2>/dev/null) && \
	if [ -n "$$WORKSPACE_URL" ]; then \
		if grep -q "^DATABRICKS_HOST=" ../.env 2>/dev/null; then \
			sed -i.bak "s|^DATABRICKS_HOST=.*|DATABRICKS_HOST=$$WORKSPACE_URL|" ../.env && rm -f ../.env.bak; \
		elif grep -q "^# DATABRICKS_HOST=" ../.env 2>/dev/null; then \
			sed -i.bak "s|^# DATABRICKS_HOST=.*|DATABRICKS_HOST=$$WORKSPACE_URL|" ../.env && rm -f ../.env.bak; \
		else \
			echo "DATABRICKS_HOST=$$WORKSPACE_URL" >> ../.env; \
		fi; \
		echo "Set DATABRICKS_HOST=$$WORKSPACE_URL"; \
	fi
	@FOUNDRY_URL=$$(terraform output -raw foundry_endpoint 2>/dev/null) && \
	if [ -n "$$FOUNDRY_URL" ]; then \
		if grep -q "^FOUNDRY_ENDPOINT=" ../.env 2>/dev/null; then \
			sed -i.bak "s|^FOUNDRY_ENDPOINT=.*|FOUNDRY_ENDPOINT=$$FOUNDRY_URL|" ../.env && rm -f ../.env.bak; \
		elif grep -q "^# FOUNDRY_ENDPOINT=" ../.env 2>/dev/null; then \
			sed -i.bak "s|^# FOUNDRY_ENDPOINT=.*|FOUNDRY_ENDPOINT=$$FOUNDRY_URL|" ../.env && rm -f ../.env.bak; \
		else \
			echo "FOUNDRY_ENDPOINT=$$FOUNDRY_URL" >> ../.env; \
		fi; \
		echo "Set FOUNDRY_ENDPOINT=$$FOUNDRY_URL"; \
	fi
