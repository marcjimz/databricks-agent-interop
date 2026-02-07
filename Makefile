# Databricks Agent Interoperability Framework
# MCP + Unity Catalog

# Load environment variables from .env
ifneq (,$(wildcard .env))
    include .env
    export
endif

# Defaults (can be overridden by .env)
UC_CATALOG ?= mcp_agents
UC_SCHEMA ?= tools

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
		echo "Error: DATABRICKS_HOST not set. Run 'make setup' and edit .env"; \
		exit 1; \
	fi
	@echo "Environment OK: $(DATABRICKS_HOST)"

# =============================================================================
# Infrastructure
# =============================================================================

deploy-infra:
	cd infra && make deploy

destroy-infra:
	cd infra && make destroy

# =============================================================================
# UC Functions
# =============================================================================

register-functions: check-env
	@echo "Import and run in Databricks: notebooks/register_uc_functions.py"
	@echo "Or run: make generate-sql | databricks sql execute"

generate-sql:
	@python -c "from src.mcp.functions import generate_registration_sql; print(generate_registration_sql('$(UC_CATALOG)', '$(UC_SCHEMA)'))"

list-functions:
	@python -c "from src.mcp.functions import FunctionRegistry; r = FunctionRegistry('$(UC_CATALOG)', '$(UC_SCHEMA)'); [print(f\"  {f['name']}: {f['description']}\") for f in r.list_functions()]"

# =============================================================================
# Testing
# =============================================================================

test-echo: check-env
	@echo "Testing echo function via MCP..."
	@TOKEN=$$(databricks auth token --host $(DATABRICKS_HOST) | jq -r '.access_token') && \
	curl -s -X POST "$(DATABRICKS_HOST)/api/2.0/mcp/functions/$(UC_CATALOG)/$(UC_SCHEMA)/echo" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"echo","arguments":{"message":"Hello from MCP!"}}}' | jq

test-calculator: check-env
	@echo "Testing calculator function via MCP..."
	@TOKEN=$$(databricks auth token --host $(DATABRICKS_HOST) | jq -r '.access_token') && \
	curl -s -X POST "$(DATABRICKS_HOST)/api/2.0/mcp/functions/$(UC_CATALOG)/$(UC_SCHEMA)/calculator" \
		-H "Authorization: Bearer $$TOKEN" \
		-H "Content-Type: application/json" \
		-d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"calculator","arguments":{"expression":"2 + 2"}}}' | jq

test: test-echo test-calculator

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

.PHONY: setup check-env deploy-infra destroy-infra register-functions generate-sql list-functions test-echo test-calculator test install unit-test lint format clean
