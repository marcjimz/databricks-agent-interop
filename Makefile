# Databricks Agent Interoperability Framework
# MCP + Unity Catalog

.PHONY: help setup check-env deploy-infra deploy-uc destroy-infra deploy-bundle deploy-apps start-apps wait-for-deployment update-agent-env grant-sp-permission test-calculator test-fhir test install unit-test lint format clean

# Load environment variables from .env
ifneq (,$(wildcard .env))
    include .env
    export
endif

# Defaults (can be overridden by .env)
UC_CATALOG ?= mcp_agents
UC_SCHEMA ?= tools

help:
	@echo "Databricks Agent Interoperability Framework"
	@echo ""
	@echo "Setup:"
	@echo "  make setup            Create .env from template"
	@echo "  make install          Install Python dependencies"
	@echo ""
	@echo "Infrastructure (two-phase deployment):"
	@echo "  make deploy-infra     Phase 1: Deploy Azure resources (Databricks + Foundry)"
	@echo "  make deploy-uc        Phase 2: Deploy UC + notebook + apps (after metastore assignment)"
	@echo "  make deploy-apps      Deploy/redeploy agents as Databricks Apps"
	@echo "  make start-apps       Start the deployed Databricks Apps"
	@echo "  make update-agent-env Fetch agent URLs and update notebooks/.env"
	@echo "  make destroy-infra    Destroy all Azure resources"
	@echo ""
	@echo "Testing:"
	@echo "  make test-calculator  Test calculator_agent function via MCP"
	@echo "  make test-fhir        Test epic_patient_search function via MCP"
	@echo "  make test             Run all MCP function tests"
	@echo "  make unit-test        Run Python unit tests"
	@echo ""
	@echo "Development:"
	@echo "  make lint             Run linter"
	@echo "  make format           Format code"
	@echo "  make clean            Clean cache files"

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

check-env:
	@if [ -z "$(DATABRICKS_HOST)" ]; then \
		echo "Error: DATABRICKS_HOST not set."; \
		echo "  - If infrastructure is not deployed: run 'make deploy-infra'"; \
		echo "  - If infrastructure is deployed: run 'cd infra && make update-env'"; \
		exit 1; \
	fi
	@echo "Using: $(DATABRICKS_HOST)"

# =============================================================================
# Infrastructure
# =============================================================================

deploy-infra:
	cd infra && $(MAKE) deploy

deploy-uc: check-env
	cd infra && $(MAKE) deploy-uc
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

grant-sp-permission: check-env
	@echo "Granting Service Principal permission on calculator-agent app..."
	@databricks apps set-permission calculator-agent --permission CAN_USE --service-principal-name mcp-interop-agent-caller 2>&1 || \
		echo "Note: Could not grant SP permission. You may need to run this manually after the app is deployed."

destroy-infra:
	cd infra && $(MAKE) destroy

# =============================================================================
# Bundle
# =============================================================================

deploy-bundle: check-env
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

deploy-apps: check-env
	@echo "Deploying agents as Databricks Apps..."
	databricks bundle deploy --var="catalog=$(UC_CATALOG)" --var="schema=$(UC_SCHEMA)"
	@echo ""
	@echo "=== Apps Deployed ==="
	@$(MAKE) start-apps
	@$(MAKE) update-agent-env

start-apps: check-env
	@echo "Starting Databricks Apps..."
	@CALC_STATE=$$(databricks apps get calculator-agent --output json 2>/dev/null | jq -r '.compute_status.state // "UNKNOWN"') && \
	if [ "$$CALC_STATE" = "ACTIVE" ]; then \
		echo "calculator-agent: already running"; \
	else \
		echo "Starting calculator-agent..." && \
		databricks apps start calculator-agent --no-wait 2>&1 || true; \
	fi
	@echo ""
	@echo "Waiting for app to be running..."
	@$(MAKE) wait-for-deployment

wait-for-deployment: check-env
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12; do \
		CALC_JSON=$$(databricks apps get calculator-agent --output json 2>/dev/null) && \
		CALC_APP=$$(echo "$$CALC_JSON" | jq -r '.app_status.state // "UNKNOWN"') && \
		CALC_DEPLOY=$$(echo "$$CALC_JSON" | jq -r '.active_deployment.status.state // .pending_deployment.status.state // "NONE"') && \
		echo "  [$$i/12] calculator-agent: app=$$CALC_APP deploy=$$CALC_DEPLOY" && \
		if [ "$$CALC_APP" = "CRASHED" ]; then \
			echo ""; \
			echo "ERROR: App crashed! Check logs in Databricks UI."; \
			exit 1; \
		fi; \
		if [ "$$CALC_APP" = "RUNNING" ] && [ "$$CALC_DEPLOY" = "SUCCEEDED" ]; then \
			echo "App deployed and running!"; \
			exit 0; \
		fi; \
		sleep 10; \
	done; \
	echo ""; \
	echo "Warning: Deployment may still be in progress."; \
	echo "Run 'make wait-for-deployment' to continue polling."

update-agent-env: check-env
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
		echo "Updated notebooks/.env"; \
	else \
		echo "Warning: URL not available yet."; \
	fi

# =============================================================================
# Testing
# =============================================================================

test-calculator: check-env
	@echo "Testing calculator_agent function via MCP..."
	@TOKEN=$$(databricks auth token --host $(DATABRICKS_HOST) | jq -r '.access_token') && \
	curl -s -X POST "$(DATABRICKS_HOST)/api/2.0/mcp/functions/$(UC_CATALOG)/$(UC_SCHEMA)/calculator_agent" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"$(UC_CATALOG)__$(UC_SCHEMA)__calculator_agent","arguments":{"expression":"add 5 and 3"}}}' | jq

test-fhir: check-env
	@echo "Testing epic_patient_search function via MCP..."
	@TOKEN=$$(databricks auth token --host $(DATABRICKS_HOST) | jq -r '.access_token') && \
	curl -s -X POST "$(DATABRICKS_HOST)/api/2.0/mcp/functions/$(UC_CATALOG)/$(UC_SCHEMA)/epic_patient_search" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"$(UC_CATALOG)__$(UC_SCHEMA)__epic_patient_search","arguments":{"family_name":"Argonaut","given_name":"","birthdate":""}}}' | jq

test: test-calculator test-fhir

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
