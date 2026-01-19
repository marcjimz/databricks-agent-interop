# Databricks notebook source
# MAGIC %md
# MAGIC # Test A2A Interoperability

# COMMAND ----------

# MAGIC %pip install httpx -q

# COMMAND ----------

dbutils.widgets.text("gateway_url", "", "A2A Gateway URL")
GATEWAY_URL = dbutils.widgets.get("gateway_url")

# COMMAND ----------

import httpx
import json

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Health Check

# COMMAND ----------

r = httpx.get(f"{GATEWAY_URL}/health")
print(r.json())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Discover Agents

# COMMAND ----------

r = httpx.get(f"{GATEWAY_URL}/api/agents")
agents = r.json()
print(json.dumps(agents, indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Send Message to Echo Agent

# COMMAND ----------

msg = {
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
        "message": {
            "messageId": "test-1",
            "role": "user",
            "parts": [{"kind": "text", "text": "Hello from Databricks!"}]
        }
    }
}

r = httpx.post(f"{GATEWAY_URL}/api/agents/echo/message", json=msg)
print(json.dumps(r.json(), indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Test Calculator Agent

# COMMAND ----------

msg["params"]["message"]["parts"][0]["text"] = "Add 42 and 17"
r = httpx.post(f"{GATEWAY_URL}/api/agents/calculator/message", json=msg)
print(json.dumps(r.json(), indent=2))
