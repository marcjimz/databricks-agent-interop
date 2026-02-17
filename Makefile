# Databricks Agent Interoperability Framework
# MCP + Unity Catalog

.PHONY: help setup check-deps check-env deploy-infra deploy-uc destroy-infra deploy-bundle deploy-apps deploy-app-code start-apps wait-for-deployment update-agent-env grant-sp-permission create-sp-secret deploy-foundry-agent delete-foundry-agent setup-foundry-oauth check-foundry-oauth deploy-mcp-agent delete-mcp-agent test-mcp-local install unit-test lint format clean clean-bundle-state outputs sync-tf-state

# Load environment variables from .env
ifneq (,$(wildcard .env))
    include .env
    export
endif

# Defaults (can be overridden by .env)
PREFIX ?= mcpagent01
LOCATION ?= westus
RESOURCE_GROUP ?= rg-mcpagent01
UC_CATALOG ?= mcp_agents
UC_SCHEMA ?= tools

help:
	@echo "Databricks Agent Interoperability Framework"
	@echo ""
	@echo "=== Deployment Flow ==="
	@echo "  1. make deploy-infra        Deploy Azure resources (Databricks + AI Foundry)"
	@echo "  2. Assign metastore         Manual step in Databricks account console"
	@echo "  3. make deploy-foundry-agent Deploy gpt-4o model + simple chat agent"
	@echo "  4. make deploy-uc           Deploy Unity Catalog + Databricks Apps"
	@echo "  5. Run notebook             Register UC functions and test"
	@echo ""
	@echo "=== Commands ==="
	@echo "  make deploy-infra         Deploy Azure infrastructure"
	@echo "  make deploy-foundry-agent Deploy Foundry agent (model + agent)"
	@echo "  make deploy-uc            Deploy Unity Catalog assets"
	@echo "  make destroy-infra        Destroy all Azure resources"
	@echo ""
	@echo "=== Foundry Agents ==="
	@echo "  make setup-foundry-oauth  Setup OAuth connection from Foundry to Databricks MCP"
	@echo "  make check-foundry-oauth  Check Foundry OAuth connection status"
	@echo "  make deploy-mcp-agent     Deploy MCP-enabled agent to Foundry portal"
	@echo "  make delete-mcp-agent     Delete MCP-enabled agent from Foundry portal"
	@echo "  make test-mcp-local       Test MCP connection locally"
	@echo ""
	@echo "=== Development ==="
	@echo "  make setup                Create .env from template"
	@echo "  make install              Install Python dependencies"
	@echo "  make clean                Clean cache files"
	@echo ""
	@echo "=== Current Configuration ==="
	@echo "  DATABRICKS_HOST=$(DATABRICKS_HOST)"
	@echo "  UC_CATALOG=$(UC_CATALOG)"
	@echo "  UC_SCHEMA=$(UC_SCHEMA)"

# =============================================================================
# Setup
# =============================================================================

setup:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example - please edit with your values"; \
	else \
		echo ".env already exists"; \
	fi

check-deps:
	@command -v terraform >/dev/null 2>&1 || { echo "Error: terraform is not installed. Install from https://terraform.io/downloads"; exit 1; }
	@command -v az >/dev/null 2>&1 || { echo "Error: Azure CLI (az) is not installed. Install from https://aka.ms/installazurecli"; exit 1; }
	@command -v databricks >/dev/null 2>&1 || { echo "Error: Databricks CLI is not installed. Install from https://docs.databricks.com/dev-tools/cli/install.html"; exit 1; }

check-env: check-deps
	@if [ -z "$(TENANT_ID)" ]; then \
		echo "Error: TENANT_ID not set. Run 'make setup' and edit .env"; \
		exit 1; \
	fi
	@if [ -z "$(SUBSCRIPTION_ID)" ]; then \
		echo "Error: SUBSCRIPTION_ID not set. Run 'make setup' and edit .env"; \
		exit 1; \
	fi

check-databricks: check-deps
	@if [ -z "$(DATABRICKS_HOST)" ]; then \
		echo "Error: DATABRICKS_HOST not set."; \
		echo "  - If infrastructure is not deployed: run 'make deploy-infra'"; \
		echo "  - If infrastructure is deployed: check .env file"; \
		exit 1; \
	fi
	@echo "Using: $(DATABRICKS_HOST)"

# Force databricks CLI to use DATABRICKS_HOST from .env (ignore ~/.databrickscfg)
export DATABRICKS_CONFIG_PROFILE=

# =============================================================================
# Infrastructure - Phase 1: Azure Resources
# =============================================================================

deploy-infra: check-env
	@echo "=== Deploying Azure Infrastructure ==="
	cd infra && terraform init
	cd infra && terraform apply -auto-approve \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)" \
		-var="resource_group_name=$(RESOURCE_GROUP)" \
		-var="deploy_uc=false"
	@$(MAKE) update-env-from-terraform
	@echo ""
	@echo "=== Phase 1 Complete ==="
	@echo "Next steps:"
	@echo "  1. Go to https://accounts.azuredatabricks.net"
	@echo "  2. Assign a metastore to workspace: $(DATABRICKS_HOST)"
	@echo "  3. Run: make deploy-foundry-agent"
	@echo "  4. Run: make deploy-uc"

# =============================================================================
# Infrastructure - Phase 2: Unity Catalog + Apps
# =============================================================================

sync-tf-state: check-databricks
	@echo "=== Syncing Terraform State with Databricks ==="
	@cd infra && ./import-existing.sh

deploy-uc: check-env check-databricks sync-tf-state
	@echo "=== Deploying Unity Catalog Resources ==="
	cd infra && terraform init
	cd infra && terraform apply -auto-approve \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)" \
		-var="resource_group_name=$(RESOURCE_GROUP)" \
		-var="uc_catalog=$(UC_CATALOG)" \
		-var="uc_schema=$(UC_SCHEMA)" \
		-var="deploy_uc=true"
	@echo ""
	@echo "=== Granting Foundry SP 'Azure AI User' role ==="
	@FOUNDRY_SP_OID=$$(cd infra && terraform output -raw foundry_sp_object_id 2>/dev/null) && \
	AI_SERVICES_ID=$$(cd infra && terraform output -raw ai_services_id 2>/dev/null) && \
	if [ -n "$$FOUNDRY_SP_OID" ] && [ -n "$$AI_SERVICES_ID" ]; then \
		echo "SP Object ID: $$FOUNDRY_SP_OID" && \
		echo "Scope: $$AI_SERVICES_ID" && \
		az role assignment create \
			--role "Azure AI User" \
			--assignee-object-id "$$FOUNDRY_SP_OID" \
			--assignee-principal-type ServicePrincipal \
			--scope "$$AI_SERVICES_ID" 2>/dev/null || echo "Role already assigned or assignment in progress"; \
	else \
		echo "Warning: Could not get Foundry SP or AI Services ID from terraform outputs."; \
	fi
	@echo ""
	@echo "=== Creating OAuth Secret for Service Principal ==="
	@cd infra && ./create-sp-secret.sh
	@echo ""
	@$(MAKE) deploy-bundle
	@$(MAKE) grant-sp-permission
	@echo ""
	@echo "=== Deployment Complete ==="
	@echo "Agent URLs have been written to notebooks/.env and synced to workspace."
	@echo ""
	@echo "Next: Open the notebook and run all cells to register UC functions:"
	@USER=$$(databricks current-user me 2>/dev/null | jq -r '.userName') && \
	echo "  $(DATABRICKS_HOST)/#workspace/Users/$$USER/.bundle/mcp-agent-interop/dev/files/notebooks/register_uc_functions"
	@echo ""
	@echo "Then test with:"
	@echo "  make test"

# =============================================================================
# Infrastructure - Destroy
# =============================================================================

destroy-infra: check-env
	@echo "=== Destroying All Azure Resources ==="
	cd infra && terraform destroy -auto-approve \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)" \
		-var="resource_group_name=$(RESOURCE_GROUP)" \
		-var="deploy_uc=true"

# =============================================================================
# Infrastructure - Utilities
# =============================================================================

outputs:
	@cd infra && terraform output

update-env-from-terraform:
	@echo "Updating .env with Terraform outputs..."
	@WORKSPACE_URL=$$(cd infra && terraform output -raw databricks_workspace_url 2>/dev/null) && \
	if [ -n "$$WORKSPACE_URL" ]; then \
		if grep -q "^DATABRICKS_HOST=" .env 2>/dev/null; then \
			sed -i.bak "s|^DATABRICKS_HOST=.*|DATABRICKS_HOST=$$WORKSPACE_URL|" .env && rm -f .env.bak; \
		else \
			echo "DATABRICKS_HOST=$$WORKSPACE_URL" >> .env; \
		fi; \
		echo "Set DATABRICKS_HOST=$$WORKSPACE_URL"; \
	fi
	@FOUNDRY_URL=$$(cd infra && terraform output -raw foundry_endpoint 2>/dev/null) && \
	if [ -n "$$FOUNDRY_URL" ]; then \
		if grep -q "^FOUNDRY_ENDPOINT=" .env 2>/dev/null; then \
			sed -i.bak "s|^FOUNDRY_ENDPOINT=.*|FOUNDRY_ENDPOINT=$$FOUNDRY_URL|" .env && rm -f .env.bak; \
		else \
			echo "FOUNDRY_ENDPOINT=$$FOUNDRY_URL" >> .env; \
		fi; \
		echo "Set FOUNDRY_ENDPOINT=$$FOUNDRY_URL"; \
	fi
	@PROJECT_URL=$$(cd infra && terraform output -raw project_endpoint 2>/dev/null) && \
	if [ -n "$$PROJECT_URL" ]; then \
		if grep -q "^AZURE_AI_PROJECT_ENDPOINT=" .env 2>/dev/null; then \
			sed -i.bak "s|^AZURE_AI_PROJECT_ENDPOINT=.*|AZURE_AI_PROJECT_ENDPOINT=$$PROJECT_URL|" .env && rm -f .env.bak; \
		else \
			echo "AZURE_AI_PROJECT_ENDPOINT=$$PROJECT_URL" >> .env; \
		fi; \
		echo "Set AZURE_AI_PROJECT_ENDPOINT=$$PROJECT_URL"; \
	fi
	@APPI_CONN=$$(cd infra && terraform output -raw application_insights_connection_string 2>/dev/null) && \
	if [ -n "$$APPI_CONN" ]; then \
		if grep -q "^APPLICATIONINSIGHTS_CONNECTION_STRING=" .env 2>/dev/null; then \
			sed -i.bak "s|^APPLICATIONINSIGHTS_CONNECTION_STRING=.*|APPLICATIONINSIGHTS_CONNECTION_STRING=$$APPI_CONN|" .env && rm -f .env.bak; \
		else \
			echo "APPLICATIONINSIGHTS_CONNECTION_STRING=$$APPI_CONN" >> .env; \
		fi; \
		echo "Set APPLICATIONINSIGHTS_CONNECTION_STRING"; \
	fi
	@APPI_APP_ID=$$(cd infra && terraform output -raw application_insights_app_id 2>/dev/null) && \
	if [ -n "$$APPI_APP_ID" ]; then \
		if grep -q "^APPLICATION_INSIGHTS_APP_ID=" .env 2>/dev/null; then \
			sed -i.bak "s|^APPLICATION_INSIGHTS_APP_ID=.*|APPLICATION_INSIGHTS_APP_ID=$$APPI_APP_ID|" .env && rm -f .env.bak; \
		else \
			echo "APPLICATION_INSIGHTS_APP_ID=$$APPI_APP_ID" >> .env; \
		fi; \
		echo "Set APPLICATION_INSIGHTS_APP_ID=$$APPI_APP_ID"; \
	fi

# =============================================================================
# Bundle Deployment
# =============================================================================

deploy-bundle: check-databricks
	@echo "=== Step 1: Deploying bundle to workspace ==="
	databricks bundle deploy --var="catalog=$(UC_CATALOG)" --var="schema=$(UC_SCHEMA)"
	@echo ""
	@echo "=== Step 2: Starting apps ==="
	@$(MAKE) start-apps
	@echo ""
	@echo "=== Step 3: Fetching agent URLs ==="
	@$(MAKE) update-agent-env
	@echo ""
	@echo "=== Step 4: Re-syncing bundle with agent URLs ==="
	databricks bundle deploy --var="catalog=$(UC_CATALOG)" --var="schema=$(UC_SCHEMA)"
	@echo ""
	@echo "=== Step 5: Granting SP permission on app ==="
	@$(MAKE) grant-sp-permission
	@echo ""
	@echo "=== Bundle Deployment Complete ==="
	@echo "Agent URLs:"
	@grep -E "^(CALCULATOR|CLAUDE)_AGENT_URL" notebooks/.env || echo "  (URLs not yet available - apps may still be starting)"

deploy-apps: check-databricks
	@echo "Deploying agents as Databricks Apps..."
	databricks bundle deploy --var="catalog=$(UC_CATALOG)" --var="schema=$(UC_SCHEMA)"
	@echo ""
	@echo "=== Apps Deployed ==="
	@$(MAKE) start-apps
	@$(MAKE) update-agent-env

start-apps: check-databricks
	@echo "Starting Databricks Apps..."
	@CALC_JSON=$$(databricks apps get calculator-agent --output json 2>/dev/null) && \
	CALC_COMPUTE=$$(echo "$$CALC_JSON" | jq -r '.compute_status.state // "UNKNOWN"') && \
	CALC_APP=$$(echo "$$CALC_JSON" | jq -r '.app_status.state // "UNKNOWN"') && \
	echo "calculator-agent: compute=$$CALC_COMPUTE app=$$CALC_APP" && \
	if [ "$$CALC_COMPUTE" != "ACTIVE" ]; then \
		echo "Starting compute..." && \
		databricks apps start calculator-agent --no-wait 2>&1 || true && \
		sleep 5; \
	fi
	@echo ""
	@echo "Deploying app code..."
	@$(MAKE) deploy-app-code
	@echo ""
	@echo "Waiting for app to be running..."
	@$(MAKE) wait-for-deployment

deploy-app-code: check-databricks
	@echo "Deploying app source code..."
	@USER=$$(databricks current-user me 2>/dev/null | jq -r '.userName') && \
	SOURCE_PATH="/Workspace/Users/$$USER/.bundle/mcp-agent-interop/dev/files/apps/calculator" && \
	echo "Source: $$SOURCE_PATH" && \
	databricks apps deploy calculator-agent --source-code-path "$$SOURCE_PATH" 2>&1 || \
	echo "Note: Deploy may have failed if already in progress. Check status with 'make wait-for-deployment'"

wait-for-deployment: check-databricks
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
		CALC_JSON=$$(databricks apps get calculator-agent --output json 2>/dev/null) && \
		CALC_APP=$$(echo "$$CALC_JSON" | jq -r '.app_status.state // "UNKNOWN"') && \
		CALC_COMPUTE=$$(echo "$$CALC_JSON" | jq -r '.compute_status.state // "UNKNOWN"') && \
		CALC_DEPLOY=$$(echo "$$CALC_JSON" | jq -r '.active_deployment.status.state // .pending_deployment.status.state // "NONE"') && \
		CALC_MSG=$$(echo "$$CALC_JSON" | jq -r '.app_status.message // ""' | head -c 60) && \
		echo "  [$$i/15] app=$$CALC_APP compute=$$CALC_COMPUTE deploy=$$CALC_DEPLOY" && \
		if [ "$$CALC_APP" = "CRASHED" ]; then \
			echo ""; \
			echo "ERROR: App crashed! Check logs in Databricks UI."; \
			echo "Message: $$CALC_MSG"; \
			exit 1; \
		fi; \
		if [ "$$CALC_APP" = "RUNNING" ]; then \
			echo "App is running!"; \
			exit 0; \
		fi; \
		if [ "$$CALC_APP" = "UNAVAILABLE" ] && [ "$$CALC_COMPUTE" = "ACTIVE" ] && [ "$$CALC_DEPLOY" = "NONE" ]; then \
			echo "Compute ready but no deployment - deploying code..." && \
			$(MAKE) deploy-app-code && \
			sleep 5; \
		else \
			sleep 10; \
		fi; \
	done; \
	echo ""; \
	echo "Warning: Deployment may still be in progress."; \
	echo "Run 'make wait-for-deployment' to continue polling."

update-agent-env: check-databricks
	@echo "Fetching agent URLs..."
	@CALC_JSON=$$(databricks apps get calculator-agent --output json 2>/dev/null) && \
	CALC_URL=$$(echo "$$CALC_JSON" | jq -r '.url // empty') && \
	CALC_COMPUTE=$$(echo "$$CALC_JSON" | jq -r '.compute_status.state // "UNKNOWN"') && \
	echo "calculator-agent: compute=$$CALC_COMPUTE url=$$CALC_URL" && \
	if [ -n "$$CALC_URL" ]; then \
		echo "# Notebook configuration - auto-generated by make deploy-bundle" > notebooks/.env && \
		echo "# Do not edit manually - sourced from root .env and app URLs" >> notebooks/.env && \
		echo "" >> notebooks/.env && \
		echo "# Unity Catalog" >> notebooks/.env && \
		echo "UC_CATALOG=$(UC_CATALOG)" >> notebooks/.env && \
		echo "UC_SCHEMA=$(UC_SCHEMA)" >> notebooks/.env && \
		echo "" >> notebooks/.env && \
		echo "# Databricks Agent URLs" >> notebooks/.env && \
		echo "CALCULATOR_AGENT_URL=$$CALC_URL" >> notebooks/.env && \
		echo "" >> notebooks/.env && \
		echo "# Azure AI Foundry Agent" >> notebooks/.env && \
		echo "AZURE_AI_PROJECT_ENDPOINT=$(AZURE_AI_PROJECT_ENDPOINT)" >> notebooks/.env && \
		echo "FOUNDRY_AGENT_ID=$(FOUNDRY_AGENT_ID)" >> notebooks/.env && \
		echo "TENANT_ID=$(TENANT_ID)" >> notebooks/.env && \
		echo "" >> notebooks/.env && \
		echo "# Azure Infrastructure (used by trace ingestion notebook)" >> notebooks/.env && \
		echo "SUBSCRIPTION_ID=$(SUBSCRIPTION_ID)" >> notebooks/.env && \
		echo "PREFIX=$(PREFIX)" >> notebooks/.env && \
		echo "RESOURCE_GROUP=$(RESOURCE_GROUP)" >> notebooks/.env && \
		echo "Updated notebooks/.env"; \
	else \
		echo "Warning: URL not available yet."; \
	fi

grant-sp-permission: check-databricks
	@echo "Granting Service Principal permission on calculator-agent app..."
	@SP_APP_ID=$$(cd infra && terraform output -raw oauth_client_id 2>/dev/null) && \
	if [ -n "$$SP_APP_ID" ] && [ "$$SP_APP_ID" != "" ]; then \
		USER_NAME=$$(databricks current-user me 2>/dev/null | jq -r '.userName') && \
		databricks apps update-permissions calculator-agent \
			--json "{\"access_control_list\": [{\"user_name\": \"$$USER_NAME\", \"permission_level\": \"CAN_MANAGE\"}, {\"service_principal_name\": \"$$SP_APP_ID\", \"permission_level\": \"CAN_USE\"}]}" && \
		echo "Granted CAN_USE to SP: $$SP_APP_ID"; \
	else \
		echo "Warning: Could not get SP application ID from terraform. Run 'make deploy-uc' first."; \
	fi

create-sp-secret: check-databricks
	@echo "=== Creating OAuth Secret for Service Principal ==="
	@SP_NAME="$(PREFIX)-agent-caller" && \
	SP_JSON=$$(databricks service-principals list --output json 2>/dev/null | jq -r ".[] | select(.displayName == \"$$SP_NAME\")") && \
	SP_ID=$$(echo "$$SP_JSON" | jq -r '.id') && \
	SP_APP_ID=$$(echo "$$SP_JSON" | jq -r '.applicationId') && \
	if [ -z "$$SP_ID" ] || [ "$$SP_ID" = "null" ]; then \
		echo "Error: Service principal '$$SP_NAME' not found. Run 'make deploy-uc' first."; \
		exit 1; \
	fi && \
	echo "Found SP: id=$$SP_ID application_id=$$SP_APP_ID" && \
	echo "Getting Azure AD token..." && \
	TOKEN=$$(az account get-access-token --resource 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d --query accessToken -o tsv 2>/dev/null) && \
	if [ -z "$$TOKEN" ]; then \
		echo "Error: Failed to get Azure AD token. Run 'az login' first."; \
		exit 1; \
	fi && \
	echo "Creating OAuth secret for service principal..." && \
	SECRET_RESPONSE=$$(curl -s -X POST \
		"$(DATABRICKS_HOST)/api/2.0/accounts/servicePrincipals/$${SP_ID}/credentials/secrets" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json") && \
	CLIENT_SECRET=$$(echo "$$SECRET_RESPONSE" | jq -r '.secret') && \
	if [ -z "$$CLIENT_SECRET" ] || [ "$$CLIENT_SECRET" = "null" ]; then \
		echo "Error creating secret:"; \
		echo "$$SECRET_RESPONSE" | jq .; \
		exit 1; \
	fi && \
	echo "OAuth secret created successfully" && \
	echo "Storing secret in scope: mcp-agent-oauth" && \
	databricks secrets put-secret mcp-agent-oauth client-secret --string-value "$$CLIENT_SECRET" && \
	echo "Done! Secret stored in mcp-agent-oauth/client-secret"

# =============================================================================
# Azure AI Foundry Agent (Standalone Project)
# =============================================================================

deploy-foundry-agent: check-env
	@echo "=== Deploying Azure AI Foundry Agent ==="
	@echo ""
	@echo "Step 1: Deploying gpt-4o model to AI Services..."
	@az cognitiveservices account deployment create \
		--name ais-$(PREFIX) \
		--resource-group $(RESOURCE_GROUP) \
		--deployment-name gpt-4o \
		--model-name gpt-4o \
		--model-version "2024-11-20" \
		--model-format OpenAI \
		--sku-capacity 10 \
		--sku-name GlobalStandard 2>/dev/null || echo "gpt-4o deployment already exists"
	@echo ""
	@echo "Step 2: Granting current user Cognitive Services permissions..."
	@USER_ID=$$(az ad signed-in-user show --query id -o tsv 2>/dev/null) && \
	if [ -n "$$USER_ID" ]; then \
		az role assignment create \
			--role "Cognitive Services OpenAI User" \
			--assignee-object-id "$$USER_ID" \
			--assignee-principal-type User \
			--scope "/subscriptions/$(SUBSCRIPTION_ID)/resourceGroups/$(RESOURCE_GROUP)/providers/Microsoft.CognitiveServices/accounts/ais-$(PREFIX)" 2>/dev/null || echo "User role already assigned"; \
	fi
	@echo ""
	@echo "Step 3: Deploying simple chat assistant (OpenAI-compatible)..."
	@pip install -q azure-ai-projects azure-identity
	@python foundry/deploy_simple_agent.py
	@echo ""
	@echo "Step 4: Saving assistant ID to .env..."
	@AGENT_ID=$$(cat foundry/.simple_agent_id 2>/dev/null) && \
	if [ -n "$$AGENT_ID" ] && [ "$${AGENT_ID:0:5}" = "asst_" ]; then \
		if grep -q "^FOUNDRY_AGENT_ID=" .env 2>/dev/null; then \
			sed -i.bak "s|^FOUNDRY_AGENT_ID=.*|FOUNDRY_AGENT_ID=$$AGENT_ID|" .env && rm -f .env.bak; \
		elif grep -q "^# FOUNDRY_AGENT_ID=" .env 2>/dev/null; then \
			sed -i.bak "s|^# FOUNDRY_AGENT_ID=.*|FOUNDRY_AGENT_ID=$$AGENT_ID|" .env && rm -f .env.bak; \
		else \
			echo "FOUNDRY_AGENT_ID=$$AGENT_ID" >> .env; \
		fi; \
		echo "Set FOUNDRY_AGENT_ID=$$AGENT_ID in .env"; \
	else \
		echo "Warning: Could not read assistant ID from foundry/.simple_agent_id"; \
	fi
	@echo ""
	@echo "=== Foundry Agent Deployed ==="
	@echo "The assistant is now available in your Foundry project."
	@echo ""
	@echo "Next: Run 'make deploy-uc' to deploy Unity Catalog assets."

delete-foundry-agent: check-env
	@echo "=== Deleting Azure AI Foundry Agent ==="
	python foundry/deploy_simple_agent.py --delete

test-mcp-local: check-env
	@echo "=== Testing Foundry + Databricks MCP Locally ==="
	python foundry/test_mcp_debug.py

deploy-mcp-agent: check-env
	@echo "=== Deploying MCP-enabled Agent to Foundry Portal ==="
	python foundry/create_agent.py

delete-mcp-agent: check-env
	@echo "=== Deleting MCP-enabled Agent from Foundry Portal ==="
	python foundry/create_agent.py --delete

setup-foundry-oauth: check-env
	@echo "=== Setting up OAuth Connection from Foundry to Databricks MCP ==="
	python foundry/setup_oauth_connection.py --create

check-foundry-oauth: check-env
	@echo "=== Checking Foundry OAuth Connection Status ==="
	python foundry/setup_oauth_connection.py --status

# =============================================================================
# Development
# =============================================================================

install:
	pip install -e ".[dev]"

unit-test:
	python -m pytest tests/ -v

lint:
	python -m ruff check src/ tests/

format:
	python -m ruff format src/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .bundle 2>/dev/null || true

clean-bundle-state:
	@echo "Cleaning Databricks bundle state..."
	rm -rf .databricks 2>/dev/null || true
	@echo "Done. Run 'make deploy-bundle' to redeploy."
