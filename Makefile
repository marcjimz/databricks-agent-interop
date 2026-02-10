# Databricks Agent Interoperability Framework
# MCP + Unity Catalog

.PHONY: help setup check-deps check-env deploy-infra deploy-uc destroy-infra deploy-bundle deploy-apps deploy-app-code start-apps wait-for-deployment update-agent-env grant-sp-permission create-sp-secret install unit-test lint format clean clean-bundle-state outputs

# Load environment variables from .env
ifneq (,$(wildcard .env))
    include .env
    export
endif

# Defaults (can be overridden by .env)
PREFIX ?= mcp-agent-interop
LOCATION ?= westus2
UC_CATALOG ?= mcp_agents
UC_SCHEMA ?= tools

help:
	@echo "Databricks Agent Interoperability Framework"
	@echo ""
	@echo "Setup:"
	@echo "  make setup              Create .env from template"
	@echo "  make install            Install Python dependencies"
	@echo ""
	@echo "Infrastructure (two-phase deployment):"
	@echo "  make deploy-infra       Phase 1: Deploy Azure resources (Databricks + Foundry)"
	@echo "  make deploy-uc          Phase 2: Deploy UC + notebook + apps (after metastore assignment)"
	@echo "  make deploy-bundle      Deploy bundle, start apps, update env, grant permissions"
	@echo "  make deploy-apps        Deploy/redeploy agents as Databricks Apps"
	@echo "  make deploy-app-code    Deploy app source code (after app is created)"
	@echo "  make start-apps         Start the deployed Databricks Apps"
	@echo "  make create-sp-secret   Create OAuth secret for Service Principal"
	@echo "  make grant-sp-permission Grant SP permission on apps"
	@echo "  make update-agent-env   Fetch agent URLs and update notebooks/.env"
	@echo "  make destroy-infra      Destroy all Azure resources"
	@echo "  make outputs            Show Terraform outputs"
	@echo ""
	@echo "Testing:"
	@echo "  make unit-test          Run Python unit tests"
	@echo ""
	@echo "Development:"
	@echo "  make lint               Run linter"
	@echo "  make format             Format code"
	@echo "  make clean              Clean cache files"
	@echo "  make clean-bundle-state Clean Databricks bundle state (fixes stale state issues)"
	@echo ""
	@echo "Configuration (from .env):"
	@echo "  TENANT_ID=$(TENANT_ID)"
	@echo "  SUBSCRIPTION_ID=$(SUBSCRIPTION_ID)"
	@echo "  LOCATION=$(LOCATION)"
	@echo "  PREFIX=$(PREFIX)"
	@echo "  DATABRICKS_HOST=$(DATABRICKS_HOST)"
	@echo "  FOUNDRY_ENDPOINT=$(FOUNDRY_ENDPOINT)"

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
		-var="deploy_uc=false"
	@$(MAKE) update-env-from-terraform
	@echo ""
	@echo "=== Phase 1 Complete ==="
	@echo "Next steps:"
	@echo "  1. Go to https://accounts.azuredatabricks.net"
	@echo "  2. Assign a metastore to workspace: $(DATABRICKS_HOST)"
	@echo "  3. Run: make deploy-uc"

# =============================================================================
# Infrastructure - Phase 2: Unity Catalog + Apps
# =============================================================================

deploy-uc: check-env check-databricks
	@echo "=== Deploying Unity Catalog Resources ==="
	cd infra && terraform init
	cd infra && terraform apply -auto-approve \
		-var="tenant_id=$(TENANT_ID)" \
		-var="subscription_id=$(SUBSCRIPTION_ID)" \
		-var="location=$(LOCATION)" \
		-var="prefix=$(PREFIX)" \
		-var="deploy_uc=true"
	@echo ""
	@echo "=== Creating OAuth Secret for Service Principal ==="
	@cd infra && ./create-sp-secret.sh || echo "Note: SP secret creation may require manual step. See docs."
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
		echo "# Agent URLs" >> notebooks/.env && \
		echo "CALCULATOR_AGENT_URL=$$CALC_URL" >> notebooks/.env && \
		echo "" >> notebooks/.env && \
		echo "# Azure AI Foundry (OAuth via Entra ID)" >> notebooks/.env && \
		echo "FOUNDRY_ENDPOINT=$(FOUNDRY_ENDPOINT)" >> notebooks/.env && \
		echo "TENANT_ID=$(TENANT_ID)" >> notebooks/.env && \
		echo "Updated notebooks/.env"; \
	else \
		echo "Warning: URL not available yet."; \
	fi

grant-sp-permission: check-databricks
	@echo "Granting Service Principal permission on calculator-agent app..."
	@SP_APP_ID=$$(databricks service-principals list --output json 2>/dev/null | jq -r '.[] | select(.displayName == "$(PREFIX)-agent-caller") | .applicationId') && \
	if [ -n "$$SP_APP_ID" ]; then \
		databricks apps update-permissions calculator-agent --json "{\"access_control_list\": [{\"user_name\": \"$$(databricks current-user me 2>/dev/null | jq -r '.userName')\", \"permission_level\": \"CAN_MANAGE\"}, {\"service_principal_name\": \"$$SP_APP_ID\", \"permission_level\": \"CAN_USE\"}]}" && \
		echo "Granted CAN_USE to SP: $$SP_APP_ID"; \
	else \
		echo "Warning: Could not find SP $(PREFIX)-agent-caller"; \
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
