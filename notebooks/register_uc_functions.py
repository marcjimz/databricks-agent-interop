# Databricks notebook source
# MAGIC %md
# MAGIC # Register UC Functions as MCP Tools
# MAGIC
# MAGIC This notebook registers UC Functions that wrap Databricks App agents,
# MAGIC automatically exposed via Databricks managed MCP servers.
# MAGIC
# MAGIC **Architecture:**
# MAGIC - Calculator Agent runs as Databricks App using MLflow AgentServer
# MAGIC - UC Functions call agents via `/invocations` using managed UC HTTP Connections
# MAGIC - MCP exposes UC Functions at `/api/2.0/mcp/functions/{catalog}/{schema}/{function}`
# MAGIC
# MAGIC **Prerequisites:**
# MAGIC - Catalog and schema exist (created by `make deploy-uc`)
# MAGIC - Agent deployed via `make deploy-bundle`
# MAGIC - CREATE CONNECTION privilege on metastore

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Configuration from .env

# COMMAND ----------

def load_env_file() -> dict:
    """Load environment variables from a .env file in the same directory as the notebook."""
    env_vars = {}
    try:
        notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
        notebook_dir = "/".join(notebook_path.rsplit("/", 1)[:-1])
        env_file_path = f"/Workspace{notebook_dir}/.env"

        with open(env_file_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
        print(f"Loaded configuration from {env_file_path}")
    except FileNotFoundError:
        print(f"Note: .env file not found. Run 'make deploy-bundle' to create it.")
    except Exception as e:
        print(f"Note: Could not load .env file: {e}")
    return env_vars

env_vars = load_env_file()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("catalog", env_vars.get("UC_CATALOG", "mcp_agents"), "Catalog")
dbutils.widgets.text("schema", env_vars.get("UC_SCHEMA", "tools"), "Schema")
dbutils.widgets.text("calculator_agent_url", env_vars.get("CALCULATOR_AGENT_URL", ""), "Calculator Agent URL")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
CALCULATOR_AGENT_URL = dbutils.widgets.get("calculator_agent_url")

if not CALCULATOR_AGENT_URL:
    raise ValueError("CALCULATOR_AGENT_URL is required. Run 'make deploy-bundle' first.")

print(f"Target: {CATALOG}.{SCHEMA}")
print(f"Calculator Agent URL: {CALCULATOR_AGENT_URL}")

spark.sql(f"USE CATALOG {CATALOG}")
try:
    spark.sql(f"DESCRIBE SCHEMA {SCHEMA}")
    print(f"Using {CATALOG}.{SCHEMA}")
except Exception as e:
    raise Exception(f"Schema {CATALOG}.{SCHEMA} does not exist. Run 'make deploy-uc' first.") from e

# COMMAND ----------

# MAGIC %md
# MAGIC ## Clean Up Existing Functions
# MAGIC
# MAGIC Remove all existing functions in the schema before registering new ones.

# COMMAND ----------

existing_functions = spark.sql(f"SHOW USER FUNCTIONS IN {SCHEMA}").collect()
for row in existing_functions:
    func_name = row["function"]
    if "." in func_name:
        func_name = func_name.split(".")[-1]
    print(f"Dropping function: {func_name}")
    spark.sql(f"DROP FUNCTION IF EXISTS {CATALOG}.{SCHEMA}.{func_name}")
print(f"Cleaned up {len(existing_functions)} functions")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup Unity Catalog HTTP Connection (OAuth M2M)
# MAGIC
# MAGIC UC functions use a managed HTTP Connection with OAuth M2M to authenticate with Databricks Apps.
# MAGIC The Service Principal credentials are stored in a Databricks secret scope (created by Terraform).
# MAGIC
# MAGIC **Benefits:**
# MAGIC - Automatic token refresh (no manual token management)
# MAGIC - Secure credential storage in secrets
# MAGIC - SP-based authentication (not user tokens)

# COMMAND ----------

import re

CONNECTION_NAME = "calculator_agent_http"
SECRET_SCOPE = "mcp-agent-oauth"

# Extract host from agent URL
match = re.match(r'(https://[^/]+)', CALCULATOR_AGENT_URL)
if not match:
    raise ValueError(f"Invalid CALCULATOR_AGENT_URL: {CALCULATOR_AGENT_URL}")
AGENT_HOST = match.group(1)

# Get workspace URL for OAuth token endpoint
workspace_url = spark.conf.get("spark.databricks.workspaceUrl")
TOKEN_ENDPOINT = f"https://{workspace_url}/oidc/v1/token"

print(f"Agent Host: {AGENT_HOST}")
print(f"Token Endpoint: {TOKEN_ENDPOINT}")
print(f"Secret Scope: {SECRET_SCOPE}")
print(f"Connection: {CONNECTION_NAME}")

# COMMAND ----------

# Verify secrets exist
try:
    client_id = dbutils.secrets.get(scope=SECRET_SCOPE, key="client-id")
    print(f"Found client-id in secret scope (length: {len(client_id)})")
except Exception as e:
    raise ValueError(f"Secret scope '{SECRET_SCOPE}' not found or missing 'client-id'. Run 'make deploy-uc' first.") from e

# COMMAND ----------

# Create HTTP connection with OAuth M2M
spark.sql(f"DROP CONNECTION IF EXISTS {CONNECTION_NAME}")
spark.sql(f"""
    CREATE CONNECTION {CONNECTION_NAME}
    TYPE HTTP
    OPTIONS (
        host '{AGENT_HOST}',
        client_id secret('{SECRET_SCOPE}', 'client-id'),
        client_secret secret('{SECRET_SCOPE}', 'client-secret'),
        oauth_scope 'all-apis',
        token_endpoint '{TOKEN_ENDPOINT}'
    )
""")
print(f"Created connection with OAuth M2M: {CONNECTION_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register Calculator Agent Function

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA}.calculator_agent(
    expression STRING COMMENT 'Natural language math expression (e.g., "add 5 and 3", "multiply 10 by 4")'
)
RETURNS STRING
COMMENT 'MCP Tool: Evaluate math expressions using the Calculator Agent. Supports add, subtract, multiply, divide.'
RETURN (
    SELECT
        CASE
            -- Handle MLflow AgentServer response format: {{"messages": [{{"content": "..."}}]}}
            WHEN get_json_object(result.text, '$.messages[0].content') IS NOT NULL
            THEN get_json_object(result.text, '$.messages[0].content')
            -- Handle Responses API format: {{"output": [{{"content": [{{"text": "..."}}]}}]}}
            WHEN get_json_object(result.text, '$.output[0].content[0].text') IS NOT NULL
            THEN get_json_object(result.text, '$.output[0].content[0].text')
            ELSE result.text
        END
    FROM (
        SELECT http_request(
            conn => '{CONNECTION_NAME}',
            method => 'POST',
            path => '/invocations',
            json => to_json(named_struct('input', array(named_struct('role', 'user', 'content', expression))))
        ) as result
    )
)
""")
print("Registered: calculator_agent")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register Epic FHIR Patient Search (Stub)

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA}.epic_patient_search(
    family_name STRING COMMENT 'Patient family (last) name to search for',
    given_name STRING COMMENT 'Patient given (first) name (use empty string if not filtering)',
    birthdate STRING COMMENT 'Patient birth date in YYYY-MM-DD format (use empty string if not filtering)'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: Search for patients in Epic FHIR (stub). Returns simulated patient data matching search criteria.'
AS $$
import json

STUB_PATIENTS = [
    {{"resourceType": "Patient", "id": "eJzlzNEKgjAYxeF3ed", "name": [{{"family": "Argonaut", "given": ["Jason"]}}], "gender": "male", "birthDate": "1985-08-01"}},
    {{"resourceType": "Patient", "id": "eAB3mDIBBcyUKaw", "name": [{{"family": "Argonaut", "given": ["Jessica"]}}], "gender": "female", "birthDate": "1988-03-15"}},
    {{"resourceType": "Patient", "id": "eq081-VQEgP8drU", "name": [{{"family": "Smith", "given": ["John"]}}], "gender": "male", "birthDate": "1970-06-20"}},
]

def matches(patient, family, given, dob):
    name = patient.get("name", [{{}}])[0]
    pf = name.get("family", "").lower()
    pg = " ".join(name.get("given", [])).lower()
    pd = patient.get("birthDate", "")
    if family.lower() not in pf: return False
    if given and given.lower() not in pg: return False
    if dob and dob != pd: return False
    return True

results = [p for p in STUB_PATIENTS if matches(p, family_name, given_name or "", birthdate or "")]
return json.dumps({{"resourceType": "Bundle", "type": "searchset", "total": len(results), "entry": [{{"resource": p}} for p in results]}})
$$
""")
print("Registered: epic_patient_search")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Registration

# COMMAND ----------

display(spark.sql(f"SHOW USER FUNCTIONS IN {SCHEMA}"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Functions

# COMMAND ----------

import requests
import json

workspace_url = spark.conf.get("spark.databricks.workspaceUrl")
token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()

# COMMAND ----------

# Test 1: Direct call to calculator agent (commented out - use Test 2 or 3 instead)
# This test uses user token which works, but the UC function uses SP OAuth token
# print("=== Test 1: Direct call to Calculator Agent ===")
# try:
#     direct_response = requests.post(
#         f"{CALCULATOR_AGENT_URL}/invocations",
#         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
#         json={"input": [{"role": "user", "content": "add 5 and 3"}]}
#     )
#     print(f"Status: {direct_response.status_code}")
#     print(f"Response: {direct_response.text[:500]}")
# except Exception as e:
#     print(f"Error: {e}")

# COMMAND ----------

# Test 2: Call UC function via SQL
print("=== Test 2: Calculator UC Function via SQL ===")
try:
    result = spark.sql(f"SELECT {CATALOG}.{SCHEMA}.calculator_agent('add 5 and 3')").collect()[0][0]
    print(f"Result: {result}")
except Exception as e:
    print(f"Error: {e}")

# COMMAND ----------

# Test 3: Call via MCP endpoint
print("=== Test 3: Calculator via MCP ===")

def call_mcp_function(function_name: str, arguments: dict) -> dict:
    """Call a UC function via the MCP server endpoint."""
    url = f"https://{workspace_url}/api/2.0/mcp/functions/{CATALOG}/{SCHEMA}/{function_name}"
    qualified_name = f"{CATALOG}__{SCHEMA}__{function_name}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": qualified_name, "arguments": arguments}}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

try:
    result = call_mcp_function("calculator_agent", {"expression": "multiply 7 by 6"})
    print(json.dumps(result, indent=2))
except Exception as e:
    print(f"Error: {e}")

# COMMAND ----------

# Test 4: Epic FHIR stub via MCP
print("=== Test 4: Epic FHIR Stub via MCP ===")
try:
    result = call_mcp_function("epic_patient_search", {"family_name": "Argonaut", "given_name": "", "birthdate": ""})
    print(json.dumps(result, indent=2))
except Exception as e:
    print(f"Error: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## MCP Endpoints

# COMMAND ----------

print(f"""
MCP Endpoints:

  calculator_agent:
  https://{workspace_url}/api/2.0/mcp/functions/{CATALOG}/{SCHEMA}/calculator_agent

  epic_patient_search:
  https://{workspace_url}/api/2.0/mcp/functions/{CATALOG}/{SCHEMA}/epic_patient_search

Test with curl:

  TOKEN=$(databricks auth token | jq -r '.access_token')

  curl -X POST "https://{workspace_url}/api/2.0/mcp/functions/{CATALOG}/{SCHEMA}/calculator_agent" \\
    -H "Authorization: Bearer $TOKEN" \\
    -H "Content-Type: application/json" \\
    -d '{{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{{"name":"{CATALOG}__{SCHEMA}__calculator_agent","arguments":{{"expression":"add 5 and 3"}}}}}}'
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Permissions Summary

# COMMAND ----------

print(f"""
=== Required Permissions ===

1. Service Principal App Access (REQUIRED - run once after deploy):
   databricks apps set-permission calculator-agent --permission CAN_USE --service-principal-name mcp-interop-agent-caller

2. UC Connection (metastore-level):
   GRANT USE CONNECTION ON CONNECTION `{CONNECTION_NAME}` TO `users`

3. UC Function Execute:
   GRANT EXECUTE ON FUNCTION {CATALOG}.{SCHEMA}.calculator_agent TO `users`
   GRANT EXECUTE ON FUNCTION {CATALOG}.{SCHEMA}.epic_patient_search TO `users`

=== Architecture ===
- Service Principal: mcp-interop-agent-caller (created by Terraform)
- OAuth credentials stored in secret scope: {SECRET_SCOPE}
- HTTP Connection uses OAuth M2M with automatic token refresh
- Token endpoint: {TOKEN_ENDPOINT}
""")
