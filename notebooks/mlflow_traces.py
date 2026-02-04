# Databricks notebook source
# MAGIC %md
# MAGIC # A2A Gateway - MLflow Traces Explorer
# MAGIC
# MAGIC Explore, query, and analyze traces from the A2A Gateway.
# MAGIC
# MAGIC **Features:**
# MAGIC 1. **View Configuration** - Current experiment and trace settings
# MAGIC 2. **Browse Traces** - View recent traces in MLflow UI
# MAGIC 3. **Query via SDK** - Search traces programmatically
# MAGIC 4. **Query via SQL** - Direct Delta table queries
# MAGIC 5. **Isolated Experiments** - Create test experiments
# MAGIC
# MAGIC > **Experimental Feature**: MLflow tracing for A2A Gateway is in Beta.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Configuration
# MAGIC
# MAGIC Load the gateway tracing configuration from settings.

# COMMAND ----------

# DBTITLE 1,Load Settings
import yaml
from pathlib import Path

# Load settings from YAML file
possible_paths = [
    Path("settings.yaml"),
    Path("notebooks/settings.yaml"),
    Path("/Workspace/") / dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get().rsplit("/", 1)[0] / "settings.yaml"
]

settings = {}
for path in possible_paths:
    try:
        if path.exists():
            with open(path) as f:
                settings = yaml.safe_load(f) or {}
            print(f"Loaded settings from: {path}")
            break
    except Exception:
        continue

# Get tracing configuration
EXPERIMENT_NAME = settings.get("mlflow_experiment_name", "/Shared/a2a-gateway-traces")
UC_SCHEMA = settings.get("trace_uc_schema", None)

# Create widgets for configuration
dbutils.widgets.text("experiment_name", EXPERIMENT_NAME, "MLflow Experiment Name")
dbutils.widgets.text("uc_schema", UC_SCHEMA or "", "UC Schema (optional)")

# COMMAND ----------

# DBTITLE 1,Get Configuration from Widgets
experiment_name = dbutils.widgets.get("experiment_name")
uc_schema = dbutils.widgets.get("uc_schema") or None

print(f"Experiment: {experiment_name}")
print(f"UC Schema: {uc_schema or 'Not configured (traces only in MLflow)'}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. View Traces in MLflow UI
# MAGIC
# MAGIC Access traces directly in the MLflow experiment UI.

# COMMAND ----------

# DBTITLE 1,Get Experiment Info
import mlflow

# Get or create the experiment
try:
    experiment = mlflow.get_experiment_by_name(experiment_name)
    if experiment:
        print(f"Experiment ID: {experiment.experiment_id}")
        print(f"Experiment Name: {experiment.name}")
        print(f"Artifact Location: {experiment.artifact_location}")
        print(f"Lifecycle Stage: {experiment.lifecycle_stage}")

        # Generate UI link
        workspace_url = spark.conf.get("spark.databricks.workspaceUrl")
        experiment_url = f"https://{workspace_url}/ml/experiments/{experiment.experiment_id}"
        print(f"\nMLflow UI: {experiment_url}")
        displayHTML(f'<a href="{experiment_url}" target="_blank">Open Experiment in MLflow UI</a>')
    else:
        print(f"Experiment '{experiment_name}' not found. It will be created when the gateway starts with tracing enabled.")
except Exception as e:
    print(f"Error accessing experiment: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Query Traces via SDK
# MAGIC
# MAGIC Use `mlflow.search_traces()` to query traces programmatically.

# COMMAND ----------

# DBTITLE 1,Search Recent Traces
import mlflow
import pandas as pd

experiment = mlflow.get_experiment_by_name(experiment_name)
if experiment:
    # Get recent traces
    traces = mlflow.search_traces(
        experiment_ids=[experiment.experiment_id],
        max_results=20
    )

    if len(traces) > 0:
        print(f"Found {len(traces)} recent traces")
        display(traces)
    else:
        print("No traces found. Make sure the gateway has tracing enabled and has received requests.")
else:
    print("Experiment not found.")

# COMMAND ----------

# DBTITLE 1,Filter Traces by Agent
# Search for traces from a specific agent
agent_name = "echo-agent"  # Change this to your agent name

experiment = mlflow.get_experiment_by_name(experiment_name)
if experiment:
    agent_traces = mlflow.search_traces(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.`agent.name` = '{agent_name}'",
        max_results=10
    )

    if len(agent_traces) > 0:
        print(f"Found {len(agent_traces)} traces for agent '{agent_name}'")
        display(agent_traces)
    else:
        print(f"No traces found for agent '{agent_name}'")

# COMMAND ----------

# DBTITLE 1,Filter Traces by User Email
# Search for traces from a specific user (OBO authentication)
user_email = "user@example.com"  # Change this to the user email

experiment = mlflow.get_experiment_by_name(experiment_name)
if experiment:
    user_traces = mlflow.search_traces(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.`user.email` = '{user_email}'",
        max_results=10
    )

    if len(user_traces) > 0:
        print(f"Found {len(user_traces)} traces for user '{user_email}'")
        display(user_traces)
    else:
        print(f"No traces found for user '{user_email}'")

# COMMAND ----------

# DBTITLE 1,Filter Traces by Request Type
# Search for different request types: agent_proxy, gateway, health
request_type = "agent_proxy"  # Change this to filter by type

experiment = mlflow.get_experiment_by_name(experiment_name)
if experiment:
    type_traces = mlflow.search_traces(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.`request.type` = '{request_type}'",
        max_results=10
    )

    if len(type_traces) > 0:
        print(f"Found {len(type_traces)} traces of type '{request_type}'")
        display(type_traces)
    else:
        print(f"No traces found of type '{request_type}'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Query Traces via SQL (Delta Table)
# MAGIC
# MAGIC If `TRACE_UC_SCHEMA` is configured, traces are synced to a Delta table every ~15 minutes.

# COMMAND ----------

# DBTITLE 1,Query Delta Table (if configured)
if uc_schema:
    # Traces are stored in a table created by MLflow Production Monitoring
    # The table name follows a pattern based on the experiment
    print(f"UC Schema configured: {uc_schema}")
    print("Traces sync to Delta every ~15 minutes.")

    # Try to find and query the traces table
    try:
        # List tables in the schema
        tables = spark.sql(f"SHOW TABLES IN {uc_schema}").collect()
        print(f"\nTables in {uc_schema}:")
        for table in tables:
            print(f"  - {table.tableName}")

        # Query traces if table exists
        # Note: The actual table name depends on how Production Monitoring was configured
        # Common patterns: gateway_traces, mlflow_traces, or experiment-based names
    except Exception as e:
        print(f"Error querying UC schema: {e}")
else:
    print("UC Schema not configured. Traces are only stored in MLflow experiment.")
    print("\nTo enable Delta table storage:")
    print("1. Set TRACE_UC_SCHEMA in gateway/app.yaml")
    print("2. Redeploy the gateway")
    print("3. Traces will sync to Delta every ~15 minutes")

# COMMAND ----------

# DBTITLE 1,Sample SQL Queries for Trace Analysis
# These queries work when traces are stored in Delta tables

sql_queries = """
-- Agent latency analysis
SELECT
  tags['agent.name'] as agent_name,
  COUNT(*) as request_count,
  AVG(duration_ms) as avg_latency_ms,
  MAX(duration_ms) as max_latency_ms,
  MIN(duration_ms) as min_latency_ms
FROM {uc_schema}.traces
WHERE tags['request.type'] = 'agent_proxy'
GROUP BY tags['agent.name']
ORDER BY avg_latency_ms DESC;

-- User activity
SELECT
  tags['user.email'] as user_email,
  tags['agent.name'] as agent_name,
  COUNT(*) as request_count
FROM {uc_schema}.traces
WHERE tags['user.authenticated'] = 'true'
GROUP BY tags['user.email'], tags['agent.name']
ORDER BY request_count DESC;

-- Error analysis
SELECT
  tags['agent.name'] as agent_name,
  tags['request.id'] as request_id,
  status,
  timestamp
FROM {uc_schema}.traces
WHERE status = 'ERROR'
ORDER BY timestamp DESC
LIMIT 100;

-- Hourly request volume
SELECT
  date_trunc('hour', timestamp) as hour,
  tags['request.type'] as request_type,
  COUNT(*) as requests
FROM {uc_schema}.traces
GROUP BY 1, 2
ORDER BY 1 DESC;
"""

print("Sample SQL queries for trace analysis:")
print("(Replace {uc_schema} with your actual schema)")
print(sql_queries)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Create Isolated Experiment
# MAGIC
# MAGIC Create a separate experiment for testing or debugging without affecting production traces.

# COMMAND ----------

# DBTITLE 1,Create Test Experiment
import mlflow
import uuid

# Get current user
username = spark.sql("SELECT current_user()").collect()[0][0]

# Create a unique test experiment
test_experiment_name = f"/Users/{username}/a2a-gateway-traces-test-{uuid.uuid4().hex[:8]}"

# Create the experiment
try:
    experiment_id = mlflow.create_experiment(test_experiment_name)
    print(f"Created test experiment: {test_experiment_name}")
    print(f"Experiment ID: {experiment_id}")

    # Set as active experiment
    mlflow.set_experiment(test_experiment_name)
    print(f"\nActive experiment set to: {test_experiment_name}")
except Exception as e:
    print(f"Error creating experiment: {e}")

# COMMAND ----------

# DBTITLE 1,Log Test Traces
import mlflow

# Ensure we're using the test experiment
test_experiment = mlflow.get_experiment_by_name(test_experiment_name)
if test_experiment:
    mlflow.set_experiment(test_experiment_name)

    # Log some test traces
    for i in range(3):
        with mlflow.start_span(name=f"test_trace_{i}") as span:
            mlflow.update_current_trace(tags={
                "gateway.version": "1.0.0",
                "gateway.environment": "test",
                "gateway.instance_id": "test-notebook",
                "request.id": f"test-req-{i}",
                "request.type": "agent_proxy",
                "agent.name": "test-agent",
                "agent.connection_id": "conn_test",
                "agent.url": "https://test.example.com",
                "agent.method": "send_message",
                "user.email": username,
                "user.authenticated": "true",
            })
            # Simulate some work
            import time
            time.sleep(0.1)

    print(f"Logged 3 test traces to {test_experiment_name}")

    # Verify traces
    traces = mlflow.search_traces(
        experiment_ids=[test_experiment.experiment_id],
        max_results=10
    )
    print(f"\nFound {len(traces)} traces in test experiment")
    display(traces)

# COMMAND ----------

# DBTITLE 1,Compare Test vs Production Traces
# Compare traces between test and production experiments
import mlflow

prod_experiment = mlflow.get_experiment_by_name(experiment_name)
test_experiment = mlflow.get_experiment_by_name(test_experiment_name)

if prod_experiment and test_experiment:
    prod_traces = mlflow.search_traces(
        experiment_ids=[prod_experiment.experiment_id],
        max_results=5
    )
    test_traces = mlflow.search_traces(
        experiment_ids=[test_experiment.experiment_id],
        max_results=5
    )

    print(f"Production experiment ({experiment_name}): {len(prod_traces)} recent traces")
    print(f"Test experiment ({test_experiment_name}): {len(test_traces)} recent traces")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Cleanup
# MAGIC
# MAGIC Delete test experiments when done.

# COMMAND ----------

# DBTITLE 1,Delete Test Experiment (Optional)
# Uncomment to delete the test experiment
# mlflow.delete_experiment(test_experiment.experiment_id)
# print(f"Deleted test experiment: {test_experiment_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC ### Trace Tags Reference
# MAGIC
# MAGIC | Tag | Description |
# MAGIC |-----|-------------|
# MAGIC | `gateway.version` | Gateway version |
# MAGIC | `gateway.environment` | Environment (dev/staging/prod) |
# MAGIC | `gateway.instance_id` | Unique gateway instance ID |
# MAGIC | `request.id` | Correlation/request ID |
# MAGIC | `request.type` | Request type (agent_proxy/gateway/health) |
# MAGIC | `user.email` | User email from OBO auth |
# MAGIC | `user.authenticated` | Whether user is authenticated |
# MAGIC | `agent.name` | Agent name (for proxy requests) |
# MAGIC | `agent.connection_id` | UC connection ID |
# MAGIC | `agent.url` | Agent URL |
# MAGIC | `agent.method` | A2A method called |
# MAGIC
# MAGIC ### Resources
# MAGIC
# MAGIC - [MLflow Tracing Documentation](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/prod-tracing)
# MAGIC - [Store Traces in Unity Catalog](https://learn.microsoft.com/en-us/azure/databricks/mlflow3/genai/tracing/trace-unity-catalog)
# MAGIC - [Search Traces Programmatically](https://docs.databricks.com/aws/en/mlflow3/genai/tracing/observe-with-traces/query-via-sdk)
