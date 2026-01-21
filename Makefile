PREFIX ?= marcin
BUNDLE_PATH ?= /Workspace/Users/marcin.jimenez@databricks.com/.bundle/a2a-gateway/dev/files

auth:
	databricks auth login

deploy:
	databricks bundle deploy
	@$(MAKE) -s redeploy

redeploy:
	@echo "Deploying apps..."
	@databricks apps deploy $(PREFIX)-a2a-gateway --source-code-path $(BUNDLE_PATH)/gateway --no-wait >/dev/null 2>&1 || true
	@databricks apps deploy $(PREFIX)-echo-agent --source-code-path $(BUNDLE_PATH)/src/agents/echo --no-wait >/dev/null 2>&1 || true
	@databricks apps deploy $(PREFIX)-calculator-agent --source-code-path $(BUNDLE_PATH)/src/agents/calculator --no-wait >/dev/null 2>&1 || true
	@echo "Done. Run 'make status' to check."

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

.PHONY: deploy status stop start destroy auth
