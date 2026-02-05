# A2A Gateway Makefile
# Supports selective deployment: databricks-only, azure-only, or all

PREFIX ?= marcin
BUNDLE_PATH ?= /Workspace/Users/marcin.jimenez@databricks.com/.bundle/a2a-gateway/dev/files
TRACE_CATALOG ?= marcin_demo
LOCATION ?= eastus

# =============================================================================
# Main Targets
# =============================================================================

deploy: deploy-all

deploy-all: deploy-databricks deploy-azure
	@echo "✅ All components deployed!"

# =============================================================================
# Databricks Targets
# =============================================================================

deploy-gateway:
	@echo "Deploying bundle resources..."
	databricks bundle deploy
	@echo "Granting USE_CATALOG on $(TRACE_CATALOG) to gateway service principal..."
	@SP_ID=$$(databricks apps get $(PREFIX)-a2a-gateway --output json 2>/dev/null | jq -r '.service_principal_client_id') && \
		databricks grants update catalog $(TRACE_CATALOG) --json "{\"changes\":[{\"add\":[\"USE_CATALOG\"],\"principal\":\"$$SP_ID\"}]}" >/dev/null 2>&1 || true
	@echo "Deploying gateway app..."
	@databricks apps deploy $(PREFIX)-a2a-gateway --source-code-path $(BUNDLE_PATH)/gateway --no-wait >/dev/null 2>&1 || true
	@echo "Starting gateway app..."
	@databricks apps start $(PREFIX)-a2a-gateway --no-wait >/dev/null 2>&1 || true
	@echo "Waiting for gateway to be running..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12; do \
		sleep 10; \
		GW_STATE=$$(databricks apps get $(PREFIX)-a2a-gateway --output json 2>/dev/null | jq -r '.compute_status.state // "PENDING"'); \
		echo "  gateway: $$GW_STATE"; \
		if [ "$$GW_STATE" = "ACTIVE" ]; then \
			echo "✅ Gateway running!"; \
			break; \
		fi; \
		if [ $$i -eq 12 ]; then \
			echo "⚠️  Timeout waiting for gateway. Run 'make status-databricks' to check."; \
		fi; \
	done

deploy-databricks: deploy-gateway
	@echo "Deploying agent apps..."
	@databricks apps deploy $(PREFIX)-echo-agent --source-code-path $(BUNDLE_PATH)/src/agents/echo --no-wait >/dev/null 2>&1 || true
	@databricks apps deploy $(PREFIX)-calculator-agent --source-code-path $(BUNDLE_PATH)/src/agents/calculator --no-wait >/dev/null 2>&1 || true
	@echo "Starting agent apps..."
	@databricks apps start $(PREFIX)-echo-agent --no-wait >/dev/null 2>&1 || true
	@databricks apps start $(PREFIX)-calculator-agent --no-wait >/dev/null 2>&1 || true
	@echo "Waiting for apps to be running..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12; do \
		sleep 10; \
		GW_STATE=$$(databricks apps get $(PREFIX)-a2a-gateway --output json 2>/dev/null | jq -r '.compute_status.state // "PENDING"'); \
		ECHO_STATE=$$(databricks apps get $(PREFIX)-echo-agent --output json 2>/dev/null | jq -r '.compute_status.state // "PENDING"'); \
		CALC_STATE=$$(databricks apps get $(PREFIX)-calculator-agent --output json 2>/dev/null | jq -r '.compute_status.state // "PENDING"'); \
		echo "  gateway: $$GW_STATE, echo: $$ECHO_STATE, calculator: $$CALC_STATE"; \
		if [ "$$GW_STATE" = "ACTIVE" ] && [ "$$ECHO_STATE" = "ACTIVE" ] && [ "$$CALC_STATE" = "ACTIVE" ]; then \
			echo "✅ All Databricks apps running!"; \
			break; \
		fi; \
		if [ $$i -eq 12 ]; then \
			echo "⚠️  Timeout waiting for apps. Run 'make status-databricks' to check."; \
		fi; \
	done
	@$(MAKE) status-databricks

status-databricks:
	@echo "=== Databricks Apps ==="
	@databricks apps get $(PREFIX)-a2a-gateway --output json 2>/dev/null | jq -r '"gateway: \(.compute_status.state) - \(.url)"' || echo "gateway: not found"
	@databricks apps get $(PREFIX)-echo-agent --output json 2>/dev/null | jq -r '"echo: \(.compute_status.state) - \(.url)"' || echo "echo: not found"
	@databricks apps get $(PREFIX)-calculator-agent --output json 2>/dev/null | jq -r '"calculator: \(.compute_status.state) - \(.url)"' || echo "calculator: not found"

stop-databricks:
	-databricks apps stop $(PREFIX)-a2a-gateway
	-databricks apps stop $(PREFIX)-echo-agent
	-databricks apps stop $(PREFIX)-calculator-agent

start-databricks:
	-databricks apps start $(PREFIX)-a2a-gateway --no-wait
	-databricks apps start $(PREFIX)-echo-agent --no-wait
	-databricks apps start $(PREFIX)-calculator-agent --no-wait

destroy-databricks:
	databricks bundle destroy --auto-approve

# =============================================================================
# Azure Targets
# =============================================================================

deploy-azure:
	@echo "Deploying Azure AI Foundry infrastructure..."
	PREFIX=$(PREFIX) LOCATION=$(LOCATION) ./infra/azure/scripts/deploy.sh

status-azure:
	@echo "=== Azure AI Foundry ==="
	@cd infra/azure/terraform && \
		if [ -f "terraform.tfstate" ]; then \
			terraform output -json 2>/dev/null | jq -r '"hub: \(.ai_foundry_hub_name.value)\nproject: \(.ai_foundry_project_name.value)\na2a-connection: \(.a2a_connection_name.value)\nportal: \(.ai_foundry_portal_url.value)"' 2>/dev/null || echo "Run 'make deploy-azure' first"; \
		else \
			echo "Not deployed. Run 'make deploy-azure' first."; \
		fi

destroy-azure:
	@echo "Destroying Azure AI Foundry infrastructure..."
	./infra/azure/scripts/deploy.sh --destroy

test-azure:
	@echo "Testing Azure AI Foundry A2A connection..."
	./infra/azure/scripts/test-agent.sh

# =============================================================================
# Combined Targets
# =============================================================================

status: status-databricks status-azure

stop: stop-databricks
	@echo "Note: Azure resources are not stopped (always-on infrastructure)"

start: start-databricks
	@echo "Note: Azure resources are always running"

destroy: destroy-databricks destroy-azure

# =============================================================================
# Auth & Testing
# =============================================================================

auth:
	databricks auth login

test:
	python -m tests.run_tests --prefix $(PREFIX)

test-unit:
	python -m pytest tests/unit/ -v

# =============================================================================
# Help
# =============================================================================

help:
	@echo "A2A Gateway Makefile"
	@echo ""
	@echo "Deployment targets:"
	@echo "  deploy-all        Deploy everything (Databricks + Azure)"
	@echo "  deploy-gateway    Deploy only the A2A gateway app"
	@echo "  deploy-databricks Deploy gateway + sample agent apps"
	@echo "  deploy-azure      Deploy Azure AI Foundry infrastructure"
	@echo ""
	@echo "Status targets:"
	@echo "  status            Show status of all components"
	@echo "  status-databricks Show Databricks apps status"
	@echo "  status-azure      Show Azure infrastructure status"
	@echo ""
	@echo "Lifecycle targets:"
	@echo "  start             Start all Databricks apps"
	@echo "  stop              Stop all Databricks apps"
	@echo "  destroy           Destroy all resources"
	@echo "  destroy-databricks Destroy Databricks resources only"
	@echo "  destroy-azure     Destroy Azure resources only"
	@echo ""
	@echo "Testing targets:"
	@echo "  test              Run integration tests"
	@echo "  test-unit         Run unit tests"
	@echo "  test-azure        Test Azure A2A connection"
	@echo ""
	@echo "Variables:"
	@echo "  PREFIX=$(PREFIX)"
	@echo "  LOCATION=$(LOCATION)"
	@echo "  TRACE_CATALOG=$(TRACE_CATALOG)"

.PHONY: deploy deploy-all deploy-gateway deploy-databricks deploy-azure \
        status status-databricks status-azure \
        stop stop-databricks start start-databricks \
        destroy destroy-databricks destroy-azure \
        auth test test-unit test-azure help
