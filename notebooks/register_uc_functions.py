# Databricks notebook source
# MAGIC %md
# MAGIC # Register UC Functions as MCP Tools
# MAGIC
# MAGIC This notebook registers UC Python Functions that wrap external agents.
# MAGIC Once registered, these functions are automatically exposed via Databricks managed MCP servers.
# MAGIC
# MAGIC ## Architecture
# MAGIC ```
# MAGIC MCP Client (Foundry, etc.)
# MAGIC        ↓ (MCP Protocol)
# MAGIC Databricks Managed MCP Server
# MAGIC        ↓ (Function Call)
# MAGIC UC Function (this notebook creates these)
# MAGIC        ↓ (HTTP/API)
# MAGIC External Agent (Foundry, APIs, etc.)
# MAGIC ```
# MAGIC
# MAGIC ## MCP Endpoint (after registration)
# MAGIC ```
# MAGIC https://<workspace>/api/2.0/mcp/functions/mcp_agents/tools/<function_name>
# MAGIC ```

# COMMAND ----------

# MAGIC %md
# MAGIC ## Install/Import the src package

# COMMAND ----------

# If running from repo, add src to path
import sys
sys.path.insert(0, "/Workspace/Repos/<your-repo>/databricks-agent-interop")

# Import the function registry
from src.mcp.functions import FunctionRegistry

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

CATALOG = "mcp_agents"
SCHEMA = "tools"

# Create the registry
registry = FunctionRegistry(catalog=CATALOG, schema=SCHEMA)

# COMMAND ----------

# MAGIC %md
# MAGIC ## View Available Functions

# COMMAND ----------

# List all functions that will be registered
for func in registry.list_functions():
    print(f"• {func['name']}: {func['description']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Generate Registration SQL
# MAGIC
# MAGIC This shows the SQL that will be executed. Review before running.

# COMMAND ----------

# Print the SQL (for review)
print(registry.get_all_functions_sql())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Execute Registration
# MAGIC
# MAGIC Run the SQL to create the catalog, schema, and functions.

# COMMAND ----------

# Create catalog and schema
spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
print(f"✓ Created {CATALOG}.{SCHEMA}")

# COMMAND ----------

# Register each function
from src.mcp.functions import EchoFunction, CalculatorFunction, FoundryAgentFunction, ExternalAPIFunction

for func_class in [EchoFunction, CalculatorFunction, FoundryAgentFunction, ExternalAPIFunction]:
    sql = func_class.get_registration_sql(CATALOG, SCHEMA)
    try:
        spark.sql(sql)
        print(f"✓ Registered {func_class.name}")
    except Exception as e:
        print(f"✗ Failed to register {func_class.name}: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Functions

# COMMAND ----------

# List all functions in the schema
functions_df = spark.sql(f"SHOW FUNCTIONS IN {CATALOG}.{SCHEMA}")
display(functions_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Echo Function

# COMMAND ----------

result = spark.sql(f"SELECT {CATALOG}.{SCHEMA}.echo('Hello from MCP!')").collect()[0][0]
print(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## MCP Endpoints
# MAGIC
# MAGIC Once registered, these functions are available via Databricks managed MCP.

# COMMAND ----------

# Get workspace URL
workspace_url = spark.conf.get("spark.databricks.workspaceUrl", "https://<workspace>")

# Print endpoints
print("MCP Endpoints:")
print("-" * 60)
for name, endpoint in registry.get_mcp_endpoints(f"https://{workspace_url}").items():
    print(f"  {name}:")
    print(f"    {endpoint}")
    print()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant Permissions
# MAGIC
# MAGIC Uncomment and modify to grant access to users/groups.

# COMMAND ----------

# Grant to all users
# print(registry.get_grant_sql("users"))
# for stmt in registry.get_grant_sql("users").split(";"):
#     if stmt.strip():
#         spark.sql(stmt)

# Grant to specific group
# for stmt in registry.get_grant_sql("data-scientists").split(";"):
#     if stmt.strip():
#         spark.sql(stmt)

print("Remember to grant EXECUTE permissions to users who need access!")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Usage Examples
# MAGIC
# MAGIC ### From Databricks (Python)
# MAGIC
# MAGIC ```python
# MAGIC from src.agents.databricks import DatabricksMCPAgent
# MAGIC
# MAGIC agent = DatabricksMCPAgent(catalog="mcp_agents", schema="tools")
# MAGIC response = agent.call_foundry_agent("my-agent", "Hello!")
# MAGIC ```
# MAGIC
# MAGIC ### From Foundry (MCP Client)
# MAGIC
# MAGIC ```python
# MAGIC from src.agents.foundry import FoundryMCPClient
# MAGIC
# MAGIC client = FoundryMCPClient(
# MAGIC     workspace_url="https://<workspace>.azuredatabricks.net",
# MAGIC     catalog="mcp_agents",
# MAGIC     schema="tools"
# MAGIC )
# MAGIC result = client.call_tool("echo", {"message": "Hello from Foundry!"})
# MAGIC ```
# MAGIC
# MAGIC ### Via curl
# MAGIC
# MAGIC ```bash
# MAGIC TOKEN=$(az account get-access-token --resource 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d -o tsv --query accessToken)
# MAGIC
# MAGIC curl -X POST "https://<workspace>/api/2.0/mcp/functions/mcp_agents/tools/echo" \
# MAGIC   -H "Authorization: Bearer $TOKEN" \
# MAGIC   -H "Content-Type: application/json" \
# MAGIC   -d '{"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "echo", "arguments": {"message": "Hello!"}}}'
# MAGIC ```
