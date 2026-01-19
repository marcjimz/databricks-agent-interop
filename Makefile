PREFIX ?= marcin
BUNDLE_PATH ?= /Workspace/Users/marcin.jimenez@databricks.com/.bundle/a2a-gateway/dev/files

deploy:
	databricks bundle deploy --force-lock
	@$(MAKE) -s deploy-app APP=$(PREFIX)-a2a-gateway SRC=$(BUNDLE_PATH)/app
	@$(MAKE) -s deploy-app APP=$(PREFIX)-echo-agent SRC=$(BUNDLE_PATH)/src/agents/echo
	@$(MAKE) -s deploy-app APP=$(PREFIX)-calculator-agent SRC=$(BUNDLE_PATH)/src/agents/calculator

deploy-app:
	@state=$$(databricks apps get $(APP) --output json 2>/dev/null | jq -r '.compute_status.state // "UNKNOWN"'); \
	if [ "$$state" = "STOPPED" ] || [ "$$state" = "ACTIVE" ]; then \
		echo "Deploying $(APP)..."; \
		databricks apps deploy $(APP) --source-code-path $(SRC) --no-wait || true; \
	else \
		echo "$(APP): $$state (skipping)"; \
	fi

status:
	@databricks apps get $(PREFIX)-a2a-gateway --output json 2>/dev/null | jq -r '"gateway: \(.compute_status.state) - \(.url)"' || echo "gateway: not found"
	@databricks apps get $(PREFIX)-echo-agent --output json 2>/dev/null | jq -r '"echo: \(.compute_status.state) - \(.url)"' || echo "echo: not found"
	@databricks apps get $(PREFIX)-calculator-agent --output json 2>/dev/null | jq -r '"calculator: \(.compute_status.state) - \(.url)"' || echo "calculator: not found"

stop:
	-databricks apps stop $(PREFIX)-a2a-gateway
	-databricks apps stop $(PREFIX)-echo-agent
	-databricks apps stop $(PREFIX)-calculator-agent

destroy:
	databricks bundle destroy --auto-approve

.PHONY: deploy deploy-app status stop destroy
