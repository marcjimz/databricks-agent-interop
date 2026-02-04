PREFIX ?= marcin
BUNDLE_PATH ?= /Workspace/Users/marcin.jimenez@databricks.com/.bundle/a2a-gateway/dev/files
TRACE_CATALOG ?= marcin_demo

auth:
	databricks auth login

deploy:
	databricks bundle deploy
	@echo "Granting USE_CATALOG on $(TRACE_CATALOG) to gateway service principal..."
	@SP_ID=$$(databricks apps get $(PREFIX)-a2a-gateway --output json 2>/dev/null | jq -r '.service_principal_client_id') && \
		databricks grants update catalog $(TRACE_CATALOG) --json "{\"changes\":[{\"add\":[\"USE_CATALOG\"],\"principal\":\"$$SP_ID\"}]}" >/dev/null 2>&1 || true
	@echo "Deploying apps..."
	@databricks apps deploy $(PREFIX)-a2a-gateway --source-code-path $(BUNDLE_PATH)/gateway --no-wait >/dev/null 2>&1 || true
	@databricks apps deploy $(PREFIX)-echo-agent --source-code-path $(BUNDLE_PATH)/src/agents/echo --no-wait >/dev/null 2>&1 || true
	@databricks apps deploy $(PREFIX)-calculator-agent --source-code-path $(BUNDLE_PATH)/src/agents/calculator --no-wait >/dev/null 2>&1 || true
	@echo "Starting apps..."
	@databricks apps start $(PREFIX)-a2a-gateway --no-wait >/dev/null 2>&1 || true
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
			echo "✅ All apps running!"; \
			break; \
		fi; \
		if [ $$i -eq 12 ]; then \
			echo "⚠️  Timeout waiting for apps. Run 'make status' to check."; \
		fi; \
	done
	@$(MAKE) status

status:
	@databricks apps get $(PREFIX)-a2a-gateway --output json 2>/dev/null | jq -r '"gateway: \(.compute_status.state) - \(.url)"' || echo "gateway: not found"
	@databricks apps get $(PREFIX)-echo-agent --output json 2>/dev/null | jq -r '"echo: \(.compute_status.state) - \(.url)"' || echo "echo: not found"
	@databricks apps get $(PREFIX)-calculator-agent --output json 2>/dev/null | jq -r '"calculator: \(.compute_status.state) - \(.url)"' || echo "calculator: not found"

stop:
	-databricks apps stop $(PREFIX)-a2a-gateway
	-databricks apps stop $(PREFIX)-echo-agent
	-databricks apps stop $(PREFIX)-calculator-agent

start:
	-databricks apps start $(PREFIX)-a2a-gateway --no-wait
	-databricks apps start $(PREFIX)-echo-agent --no-wait
	-databricks apps start $(PREFIX)-calculator-agent --no-wait

destroy:
	databricks bundle destroy --auto-approve

test:
	python -m tests.run_tests --prefix $(PREFIX)

test-unit:
	python -m pytest tests/unit/ -v

.PHONY: deploy status stop start destroy auth test test-unit
