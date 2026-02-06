# A2A Gateway Makefile
# Configure config/.env then run: make deploy

# Load config
-include config/.env
export

# Required variables (set in config/.env)
ENTRA_TENANT_ID ?=
DATABRICKS_HOST ?=
DATABRICKS_WORKSPACE_ID ?=
APIM_PUBLISHER_EMAIL ?=

# Optional variables
ENVIRONMENT ?= dev
LOCATION ?= eastus2
PREFIX ?= a2a

.PHONY: help deploy deploy-agents destroy destroy-agents status register-agents register grant revoke token test test-unit test-compliance test-agents

help:
	@echo "A2A Gateway Commands:"
	@echo ""
	@echo "Quick Start:"
	@echo "  make deploy              Deploy APIM gateway (Terraform)"
	@echo "  make deploy-agents       Deploy echo/calculator agents (Databricks Apps)"
	@echo "  make register-agents USER=x   Register deployed agents + grant access"
	@echo "  make test-agents         Test echo and calculator agents"
	@echo ""
	@echo "Infrastructure:"
	@echo "  make destroy             Destroy APIM infrastructure"
	@echo "  make destroy-agents      Destroy Databricks agents"
	@echo "  make status              Show gateway URL and agent URLs"
	@echo ""
	@echo "Register Other Agents:"
	@echo "  make register-databricks NAME=x HOST=y   Databricks agent (token passthrough)"
	@echo "  make register-external NAME=x HOST=y     External agent (optional TOKEN=z)"
	@echo ""
	@echo "Access Control:"
	@echo "  make grant NAME=x USER=y      Grant USE_CONNECTION to user"
	@echo "  make revoke NAME=x USER=y     Revoke USE_CONNECTION from user"
	@echo ""
	@echo "Setup: cp config/.env.example config/.env && edit && make deploy"

# === Infrastructure ===

deploy:
	@if [ -z "$(ENTRA_TENANT_ID)" ]; then echo "Error: Set ENTRA_TENANT_ID in config/.env"; exit 1; fi
	@if [ -z "$(DATABRICKS_HOST)" ]; then echo "Error: Set DATABRICKS_HOST in config/.env"; exit 1; fi
	@if [ -z "$(DATABRICKS_WORKSPACE_ID)" ]; then echo "Error: Set DATABRICKS_WORKSPACE_ID in config/.env"; exit 1; fi
	@if [ -z "$(APIM_PUBLISHER_EMAIL)" ]; then echo "Error: Set APIM_PUBLISHER_EMAIL in config/.env"; exit 1; fi
	cd infra && terraform init
	cd infra && terraform apply \
		-var="entra_tenant_id=$(ENTRA_TENANT_ID)" \
		-var="databricks_host=$(DATABRICKS_HOST)" \
		-var="databricks_workspace_id=$(DATABRICKS_WORKSPACE_ID)" \
		-var="apim_publisher_email=$(APIM_PUBLISHER_EMAIL)" \
		-var="environment=$(ENVIRONMENT)" \
		-var="location=$(LOCATION)"
	@$(MAKE) status

destroy:
	cd infra && terraform destroy \
		-var="entra_tenant_id=$(ENTRA_TENANT_ID)" \
		-var="databricks_host=$(DATABRICKS_HOST)" \
		-var="databricks_workspace_id=$(DATABRICKS_WORKSPACE_ID)" \
		-var="apim_publisher_email=$(APIM_PUBLISHER_EMAIL)"

deploy-agents:
	databricks bundle deploy --var="name_prefix=$(PREFIX)"
	@echo ""
	@echo "Agents deployed. Register with: make register-agents USER=user@example.com"

destroy-agents:
	databricks bundle destroy --var="name_prefix=$(PREFIX)"

# Register the deployed echo and calculator agents automatically
register-agents:
	@if [ -z "$(USER)" ]; then echo "Usage: make register-agents USER=user@example.com"; exit 1; fi
	@echo "Registering deployed agents..."
	@ECHO_URL=$$(databricks apps list --output json | python3 -c "import sys,json; apps=json.load(sys.stdin).get('apps',[]); url=[a.get('url','') for a in apps if a['name']=='$(PREFIX)-echo-agent']; print(url[0] if url else '')") && \
	if [ -n "$$ECHO_URL" ]; then \
		echo "Registering echo agent: $$ECHO_URL"; \
		python scripts/create_agent_connection.py --name echo --host $$ECHO_URL --base-path /a2a --bearer-token databricks; \
		databricks grants update connection echo-a2a --json '{"changes":[{"add":["USE_CONNECTION"],"principal":"$(USER)"}]}'; \
	else \
		echo "Echo agent not found"; \
	fi
	@CALC_URL=$$(databricks apps list --output json | python3 -c "import sys,json; apps=json.load(sys.stdin).get('apps',[]); url=[a.get('url','') for a in apps if a['name']=='$(PREFIX)-calculator-agent']; print(url[0] if url else '')") && \
	if [ -n "$$CALC_URL" ]; then \
		echo "Registering calculator agent: $$CALC_URL"; \
		python scripts/create_agent_connection.py --name calculator --host $$CALC_URL --base-path /a2a --bearer-token databricks; \
		databricks grants update connection calculator-a2a --json '{"changes":[{"add":["USE_CONNECTION"],"principal":"$(USER)"}]}'; \
	else \
		echo "Calculator agent not found"; \
	fi
	@echo ""
	@echo "Done. Test with: make test-agents"

status:
	@echo ""
	@echo "=== Gateway ==="
	@cd infra && terraform output -raw a2a_gateway_base_url 2>/dev/null || echo "  (not deployed)"
	@echo ""
	@echo ""
	@echo "=== Deployed Agents ==="
	@databricks apps list --output json 2>/dev/null | python3 -c "import sys,json; apps=json.load(sys.stdin).get('apps',[]); [print(f\"  {a['name']}: {a.get('url','(pending)')}\") for a in apps if '$(PREFIX)' in a['name']]" 2>/dev/null || echo "  (none or databricks CLI not configured)"
	@echo ""

# === Agent Management ===

# Register a Databricks-hosted agent (same tenant, token passthrough)
register-databricks:
	@if [ -z "$(NAME)" ]; then echo "Usage: make register-databricks NAME=myagent HOST=https://..."; exit 1; fi
	@if [ -z "$(HOST)" ]; then echo "Usage: make register-databricks NAME=myagent HOST=https://..."; exit 1; fi
	python scripts/create_agent_connection.py \
		--name $(NAME) \
		--host $(HOST) \
		--base-path $(or $(BASE_PATH),/a2a) \
		--bearer-token databricks

# Register an external agent (static token or no auth)
register-external:
	@if [ -z "$(NAME)" ]; then echo "Usage: make register-external NAME=myagent HOST=https://... [TOKEN=xxx]"; exit 1; fi
	@if [ -z "$(HOST)" ]; then echo "Usage: make register-external NAME=myagent HOST=https://... [TOKEN=xxx]"; exit 1; fi
	python scripts/create_agent_connection.py \
		--name $(NAME) \
		--host $(HOST) \
		--base-path $(or $(BASE_PATH),/.well-known/agent.json) \
		$(if $(TOKEN),--bearer-token $(TOKEN),)

# Generic register (specify all options)
register:
	@if [ -z "$(NAME)" ]; then echo "Usage: make register NAME=x HOST=y [BASE_PATH=z] [TOKEN=t]"; exit 1; fi
	@if [ -z "$(HOST)" ]; then echo "Usage: make register NAME=x HOST=y [BASE_PATH=z] [TOKEN=t]"; exit 1; fi
	python scripts/create_agent_connection.py \
		--name $(NAME) \
		--host $(HOST) \
		$(if $(BASE_PATH),--base-path $(BASE_PATH),) \
		$(if $(TOKEN),--bearer-token $(TOKEN),)

grant:
	@if [ -z "$(NAME)" ]; then echo "Usage: make grant NAME=myagent USER=user@example.com"; exit 1; fi
	@if [ -z "$(USER)" ]; then echo "Usage: make grant NAME=myagent USER=user@example.com"; exit 1; fi
	databricks grants update connection $(NAME)-a2a --json '{"changes":[{"add":["USE_CONNECTION"],"principal":"$(USER)"}]}'

revoke:
	@if [ -z "$(NAME)" ]; then echo "Usage: make revoke NAME=myagent USER=user@example.com"; exit 1; fi
	@if [ -z "$(USER)" ]; then echo "Usage: make revoke NAME=myagent USER=user@example.com"; exit 1; fi
	databricks grants update connection $(NAME)-a2a --json '{"changes":[{"remove":["USE_CONNECTION"],"principal":"$(USER)"}]}'

# === Auth ===

token:
	@az account get-access-token --resource https://management.azure.com --query accessToken -o tsv

# === Testing ===

test: test-unit test-compliance

test-unit:
	pytest tests/unit/ -v

test-integration:
	@GATEWAY_URL=$$(cd infra && terraform output -raw a2a_gateway_base_url) && \
	APIM_GATEWAY_URL=$$GATEWAY_URL DATABRICKS_TOKEN=$$($(MAKE) -s token) pytest tests/integration/ -v

test-compliance:
	python scripts/test_agent_card_compliance.py --mock

test-agents:
	@GATEWAY_URL=$$(cd infra && terraform output -raw a2a_gateway_base_url 2>/dev/null) && \
	TOKEN=$$(az account get-access-token --resource https://management.azure.com --query accessToken -o tsv) && \
	echo "Gateway: $$GATEWAY_URL" && \
	echo "" && \
	echo "=== List Agents ===" && \
	curl -s -H "Authorization: Bearer $$TOKEN" "$$GATEWAY_URL/agents" | python3 -m json.tool && \
	echo "" && \
	echo "=== Echo Agent ===" && \
	curl -s -X POST "$$GATEWAY_URL/agents/echo" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"role":"user","parts":[{"type":"text","text":"Hello!"}]}}}' | python3 -m json.tool && \
	echo "" && \
	echo "=== Calculator Agent ===" && \
	curl -s -X POST "$$GATEWAY_URL/agents/calculator" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '{"jsonrpc":"2.0","id":"2","method":"message/send","params":{"message":{"role":"user","parts":[{"type":"text","text":"What is 42 + 17?"}]}}}' | python3 -m json.tool
