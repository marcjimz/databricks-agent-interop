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
dbutils.widgets.text("foundry_project_endpoint", env_vars.get("AZURE_AI_PROJECT_ENDPOINT", ""), "Foundry Project Endpoint")
dbutils.widgets.text("foundry_agent_id", env_vars.get("FOUNDRY_AGENT_ID", ""), "Foundry Agent ID (asst_xxx)")
dbutils.widgets.text("tenant_id", env_vars.get("TENANT_ID", ""), "Azure Tenant ID")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
CALCULATOR_AGENT_URL = dbutils.widgets.get("calculator_agent_url")
FOUNDRY_PROJECT_ENDPOINT = dbutils.widgets.get("foundry_project_endpoint")
FOUNDRY_AGENT_ID = dbutils.widgets.get("foundry_agent_id")
TENANT_ID = dbutils.widgets.get("tenant_id")

# Validate required configuration
if not CALCULATOR_AGENT_URL:
    raise ValueError("CALCULATOR_AGENT_URL is required. Run 'make deploy-bundle' first.")
if not FOUNDRY_PROJECT_ENDPOINT:
    raise ValueError("AZURE_AI_PROJECT_ENDPOINT is required. Run 'make deploy-foundry-agent' first.")
if not FOUNDRY_AGENT_ID:
    raise ValueError("FOUNDRY_AGENT_ID is required. Run 'make deploy-foundry-agent' and copy the assistant ID.")
if not FOUNDRY_AGENT_ID.startswith("asst_"):
    raise ValueError(f"FOUNDRY_AGENT_ID must start with 'asst_', got: {FOUNDRY_AGENT_ID}")
if not TENANT_ID:
    raise ValueError("TENANT_ID is required for Azure AD OAuth. Check notebooks/.env.")

print(f"Target: {CATALOG}.{SCHEMA}")
print(f"Calculator Agent URL: {CALCULATOR_AGENT_URL}")
print(f"Foundry Project Endpoint: {FOUNDRY_PROJECT_ENDPOINT}")
print(f"Foundry Agent ID: {FOUNDRY_AGENT_ID}")
print(f"Tenant ID: {TENANT_ID}")

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

# Retrieve OAuth credentials from secret scope
# Note: secret() function only works for bearer_token, not for OAuth options.
# We retrieve the values and pass them as literals - UC protects the connection object.
try:
    client_id = dbutils.secrets.get(scope=SECRET_SCOPE, key="client-id")
    client_secret = dbutils.secrets.get(scope=SECRET_SCOPE, key="client-secret")
    print(f"Retrieved OAuth credentials from secret scope '{SECRET_SCOPE}'")
except Exception as e:
    raise ValueError(f"Secret scope '{SECRET_SCOPE}' not found or missing credentials. Run 'make deploy-uc' first.") from e

# COMMAND ----------

# Create HTTP connection with OAuth M2M
spark.sql(f"DROP CONNECTION IF EXISTS {CONNECTION_NAME}")
spark.sql(f"""
    CREATE CONNECTION {CONNECTION_NAME}
    TYPE HTTP
    OPTIONS (
        host '{AGENT_HOST}',
        client_id '{client_id}',
        client_secret '{client_secret}',
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
return "[EpicFHIR] " + json.dumps({{"resourceType": "Bundle", "type": "searchset", "total": len(results), "entry": [{{"resource": p}} for p in results]}})
$$
""")
print("Registered: epic_patient_search")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register Azure AI Foundry Agent
# MAGIC
# MAGIC This function calls a **real Azure AI Foundry Agent** (not just a model endpoint),
# MAGIC demonstrating true cross-platform agent-to-agent interoperability via MCP.
# MAGIC
# MAGIC The Python UC Function handles the full Agents API flow:
# MAGIC 1. Authenticate with Azure AD (Service Principal)
# MAGIC 2. Create a thread
# MAGIC 3. Add the user message
# MAGIC 4. Run the agent
# MAGIC 5. Poll for completion
# MAGIC 6. Return the agent's response

# COMMAND ----------

# Get Foundry SP credentials for Python UC Function
# These are stored in the secret scope and embedded in the function.
foundry_client_id = dbutils.secrets.get(scope=SECRET_SCOPE, key="foundry-client-id")
foundry_client_secret = dbutils.secrets.get(scope=SECRET_SCOPE, key="foundry-client-secret")
print(f"Retrieved Foundry OAuth credentials from secret scope")
print(f"Foundry Project Endpoint: {FOUNDRY_PROJECT_ENDPOINT}")
print(f"Foundry Agent ID: {FOUNDRY_AGENT_ID}")

# COMMAND ----------

# Register Foundry Agent function (Python)
# Calls a real Azure AI Foundry Agent using the Agents API.
# Authenticates with Azure AD Service Principal and handles the full thread/run lifecycle.
spark.sql(f"""
CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA}.foundry_agent(
    message STRING COMMENT 'Message to send to the Azure AI Foundry Agent'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: Chat with a real Azure AI Foundry Agent. Demonstrates cross-platform agent-to-agent interoperability between Databricks and Azure AI Foundry.'
AS $$
import json
import time
import urllib.request
import urllib.parse
import urllib.error

# Configuration (embedded at function creation time)
TENANT_ID = "{TENANT_ID}"
CLIENT_ID = "{foundry_client_id}"
CLIENT_SECRET = "{foundry_client_secret}"
PROJECT_ENDPOINT = "{FOUNDRY_PROJECT_ENDPOINT}"
ASSISTANT_ID = "{FOUNDRY_AGENT_ID}"
API_VERSION = "2025-05-15-preview"
TIMEOUT = 60

def get_token():
    \"\"\"Get Azure AD token using client credentials.\"\"\"
    url = f"https://login.microsoftonline.com/{{TENANT_ID}}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({{
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://ai.azure.com/.default"
    }}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())["access_token"]

def api_call(method, path, token, body=None):
    \"\"\"Make API call to Foundry. Threads/messages/runs are at project level.\"\"\"
    url = f"{{PROJECT_ENDPOINT}}{{path}}?api-version={{API_VERSION}}"
    headers = {{"Authorization": f"Bearer {{token}}", "Content-Type": "application/json"}}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        return {{"error": error_body, "status": e.code}}

def call_foundry_agent(user_message):
    \"\"\"Call the Foundry agent and return the response.\"\"\"
    try:
        token = get_token()

        # Create thread
        thread = api_call("POST", "/threads", token, {{}})
        if "error" in thread:
            return f"[Foundry Agent] Error creating thread: {{thread['error']}}"
        thread_id = thread.get("id")

        # Add message
        api_call("POST", f"/threads/{{thread_id}}/messages", token,
                 {{"role": "user", "content": user_message}})

        # Run agent
        run = api_call("POST", f"/threads/{{thread_id}}/runs", token,
                       {{"assistant_id": ASSISTANT_ID}})
        if "error" in run:
            return f"[Foundry Agent] Error starting run: {{run['error']}}"
        run_id = run.get("id")

        # Poll for completion
        start = time.time()
        while time.time() - start < TIMEOUT:
            status = api_call("GET", f"/threads/{{thread_id}}/runs/{{run_id}}", token)
            if status.get("status") == "completed":
                break
            elif status.get("status") in ["failed", "cancelled", "expired"]:
                return f"[Foundry Agent] Run {{status.get('status')}}"
            time.sleep(0.5)
        else:
            return "[Foundry Agent] Timeout waiting for response"

        # Get response
        messages = api_call("GET", f"/threads/{{thread_id}}/messages", token)
        if "data" in messages and messages["data"]:
            msg = messages["data"][0]
            for content in msg.get("content", []):
                if content.get("type") == "text":
                    response_text = content.get("text", {{}}).get("value", "")
                    return f"[Foundry Agent] {{response_text}}"

        return "[Foundry Agent] No response content"

    except Exception as e:
        return f"[Foundry Agent] Error: {{str(e)}}"

return call_foundry_agent(message)
$$
""")
print("Registered: foundry_agent")

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

# Test 1: Call UC function via SQL
print("=== Test 1: Calculator UC Function via SQL ===")
try:
    result = spark.sql(f"SELECT {CATALOG}.{SCHEMA}.calculator_agent('add 5 and 3')").collect()[0][0]
    print(f"Result: {result}")
except Exception as e:
    print(f"Error: {e}")

# COMMAND ----------

# Test 2: Call via MCP endpoint
print("=== Test 2: Calculator via MCP ===")

def call_mcp_function(function_name: str, arguments: dict) -> dict:
    """Call a UC function via the MCP server endpoint."""
    url = f"https://{workspace_url}/api/2.0/mcp/functions/{CATALOG}/{SCHEMA}/{function_name}"
    qualified_name = f"{CATALOG}__{SCHEMA}__{function_name}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Ensure arguments values are JSON-serializable (convert callables to their string repr)
    clean_arguments = {}
    for k, v in arguments.items():
        if callable(v):
            print(f"WARNING: argument '{k}' is a callable, converting to string")
            clean_arguments[k] = str(v)
        else:
            clean_arguments[k] = v

    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {
            "name": str(qualified_name),
            "arguments": clean_arguments
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

try:
    result = call_mcp_function("calculator_agent", {"expression": "multiply 7 by 6"})
    print(json.dumps(result, indent=2))
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()

# COMMAND ----------

# Test 3: Epic FHIR stub via MCP
print("=== Test 3: Epic FHIR Stub via MCP ===")
try:
    result = call_mcp_function("epic_patient_search", {"family_name": "Argonaut", "given_name": "", "birthdate": ""})
    # Handle case where result might contain non-serializable objects
    if callable(result):
        print(f"Error: result is a callable: {result}")
    else:
        print(json.dumps(result, indent=2))
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()

# COMMAND ----------

# Test 4: Azure AI Foundry chat agent via MCP
print("=== Test 4: Foundry Chat Agent via MCP ===")
try:
    result = call_mcp_function("foundry_agent", {"message": "What is 2 + 2? Answer briefly."})
    print(json.dumps(result, indent=2))
except Exception as e:
    import traceback
    print(f"Error: {e}")
    traceback.print_exc()

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

  foundry_agent:
  https://{workspace_url}/api/2.0/mcp/functions/{CATALOG}/{SCHEMA}/foundry_agent

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
   make grant-sp-permission

2. UC Connection (metastore-level):
   GRANT USE CONNECTION ON CONNECTION `{CONNECTION_NAME}` TO `users`

3. UC Function Execute:
   GRANT EXECUTE ON FUNCTION {CATALOG}.{SCHEMA}.calculator_agent TO `users`
   GRANT EXECUTE ON FUNCTION {CATALOG}.{SCHEMA}.epic_patient_search TO `users`
   GRANT EXECUTE ON FUNCTION {CATALOG}.{SCHEMA}.foundry_agent TO `users`

=== Architecture ===
- Databricks Service Principal for calculator-agent (OAuth M2M)
- Azure AD Service Principal for Foundry (Entra ID OAuth M2M)
- OAuth credentials stored in secret scope: {SECRET_SCOPE}
- Calculator: UC HTTP Connection with OAuth M2M (token endpoint: {TOKEN_ENDPOINT})
- Foundry: Python UC Function with embedded SP credentials (Azure AD token)
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8: Audit & Governance
# MAGIC
# MAGIC Unity Catalog logs all function access. Use these queries to monitor MCP tool usage.

# COMMAND ----------

# MAGIC %md
# MAGIC ### View Function Access (Audit Logs)
# MAGIC
# MAGIC `system.access.audit` tracks when functions are accessed via `getFunction` action.

# COMMAND ----------

spark.sql(f"""
SELECT
    event_time,
    user_identity.email as user,
    request_params.full_name_arg as function_name,
    source_ip_address,
    user_agent
FROM system.access.audit
WHERE action_name = 'getFunction'
  AND request_params.full_name_arg LIKE '{CATALOG}.{SCHEMA}.%'
ORDER BY event_time DESC
LIMIT 100
""").display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### View Function Permission Grants
# MAGIC
# MAGIC Uses `information_schema.routine_privileges` to show who has access to functions.

# COMMAND ----------

# Query routine (function) privileges
spark.sql(f"""
SELECT
    grantee,
    privilege_type,
    routine_name,
    inherited_from
FROM system.information_schema.routine_privileges
WHERE routine_catalog = '{CATALOG}'
  AND routine_schema = '{SCHEMA}'
ORDER BY routine_name, grantee
""").display()
