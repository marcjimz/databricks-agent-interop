# Databricks notebook source
# MAGIC %md
# MAGIC # Register A2A Agent Connections
# MAGIC
# MAGIC Creates UC connections for deployed agents so the gateway can discover them.

# COMMAND ----------

dbutils.widgets.text("echo_agent_url", "", "Echo Agent URL")
dbutils.widgets.text("calculator_agent_url", "", "Calculator Agent URL")

ECHO_URL = dbutils.widgets.get("echo_agent_url")
CALC_URL = dbutils.widgets.get("calculator_agent_url")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Echo Agent Connection

# COMMAND ----------

if ECHO_URL:
    spark.sql(f"""
        CREATE CONNECTION IF NOT EXISTS `echo-a2a` TYPE HTTP
        OPTIONS (url = '{ECHO_URL}')
        COMMENT 'Echo Agent - Returns messages for A2A testing'
    """)
    print(f"Created echo-a2a connection: {ECHO_URL}")
else:
    print("Skipped - no URL provided")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Calculator Agent Connection

# COMMAND ----------

if CALC_URL:
    spark.sql(f"""
        CREATE CONNECTION IF NOT EXISTS `calculator-a2a` TYPE HTTP
        OPTIONS (url = '{CALC_URL}')
        COMMENT 'Calculator Agent - Basic arithmetic operations'
    """)
    print(f"Created calculator-a2a connection: {CALC_URL}")
else:
    print("Skipped - no URL provided")

# COMMAND ----------

# MAGIC %md
# MAGIC ## List A2A Connections

# COMMAND ----------

# MAGIC %sql
# MAGIC SHOW CONNECTIONS LIKE '*-a2a'

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant Access (Optional)

# COMMAND ----------

# Uncomment to grant access to a group
# spark.sql("GRANT USE CONNECTION ON CONNECTION `echo-a2a` TO `data-scientists`")
# spark.sql("GRANT USE CONNECTION ON CONNECTION `calculator-a2a` TO `data-scientists`")
