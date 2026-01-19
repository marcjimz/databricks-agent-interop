# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy A2A Apps via DAB
# MAGIC
# MAGIC Deploys the A2A Gateway and demo agents using Databricks Asset Bundles.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deploy All Apps

# COMMAND ----------

# MAGIC %sh
# MAGIC # Navigate to repo root and deploy
# MAGIC cd /Workspace/Repos/${DATABRICKS_USER}/databricks-a2a-gateway
# MAGIC databricks bundle deploy --target dev

# COMMAND ----------

# MAGIC %md
# MAGIC ## Or Deploy Apps Individually

# COMMAND ----------

# Deploy gateway only
# %sh
# databricks apps deploy a2a-gateway --source-code-path ./app

# COMMAND ----------

# Deploy echo agent only
# %sh
# databricks apps deploy echo-agent --source-code-path ./src/agents

# COMMAND ----------

# MAGIC %md
# MAGIC ## Check Deployment Status

# COMMAND ----------

# MAGIC %sh
# MAGIC databricks apps list

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get App URLs

# COMMAND ----------

# MAGIC %sh
# MAGIC echo "=== A2A Gateway ==="
# MAGIC databricks apps get a2a-gateway --output json | jq -r '.url // "Not deployed"'
# MAGIC echo ""
# MAGIC echo "=== Echo Agent ==="
# MAGIC databricks apps get echo-agent --output json | jq -r '.url // "Not deployed"'
# MAGIC echo ""
# MAGIC echo "=== Calculator Agent ==="
# MAGIC databricks apps get calculator-agent --output json | jq -r '.url // "Not deployed"'
