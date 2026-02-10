"""
UC Function: External API Wrapper

Defines the UC Python Function that calls external APIs using
credentials stored in UC Connections.

Usage:
    1. Create a UC Connection with API credentials
    2. Register this function using FunctionRegistry
    3. Call via MCP or directly in Databricks
"""

# The Python code that runs inside the UC Function
EXTERNAL_API_FUNCTION_CODE = '''
import json
import requests
from datetime import datetime, timedelta
from pyspark.sql import SparkSession

# Token cache for OAuth M2M flows
_token_cache = {}

def _get_oauth_token(endpoint: str, client_id: str, client_secret: str, scope: str) -> str:
    """Acquire and cache OAuth M2M token."""
    cache_key = f"{endpoint}:{client_id}"

    if cache_key in _token_cache:
        token, expires_at = _token_cache[cache_key]
        if datetime.now() < expires_at:
            return token

    response = requests.post(
        endpoint,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10
    )
    response.raise_for_status()
    data = response.json()

    token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    _token_cache[cache_key] = (token, datetime.now() + timedelta(seconds=expires_in - 60))

    return token


def call_external_api(
    connection_name: str,
    method: str,
    path: str,
    body: str = None,
    headers_json: str = None
) -> str:
    """
    Call an external API using credentials from a UC Connection.

    Supports:
    - Static bearer tokens
    - OAuth M2M (client credentials flow)
    - No auth (for public APIs)

    Args:
        connection_name: Name of the UC HTTP Connection
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API path to call
        body: Optional request body as JSON string
        headers_json: Optional additional headers as JSON string

    Returns:
        JSON string with API response
    """
    spark = SparkSession.builder.getOrCreate()

    # Get connection details from UC
    try:
        conn_df = spark.sql(f"DESCRIBE CONNECTION `{connection_name}`")
        conn = {row["info_name"]: row["info_value"] for row in conn_df.collect()}
    except Exception as e:
        return json.dumps({
            "error": f"Connection not found: {connection_name}",
            "detail": str(e)
        })

    host = conn.get("host", "")
    base_path = conn.get("base_path", "")
    bearer_token = conn.get("bearer_token", "")

    if not host:
        return json.dumps({"error": "Connection missing 'host' property"})

    # Determine authentication method
    token = None
    if bearer_token == "oauth":
        # OAuth M2M flow
        client_id = conn.get("client_id", "")
        client_secret = conn.get("client_secret", "")
        token_endpoint = conn.get("token_endpoint", "")
        scope = conn.get("oauth_scope", "")

        if not all([client_id, client_secret, token_endpoint]):
            return json.dumps({"error": "OAuth connection missing credentials"})

        try:
            token = _get_oauth_token(token_endpoint, client_id, client_secret, scope)
        except Exception as e:
            return json.dumps({"error": f"OAuth token acquisition failed: {str(e)}"})

    elif bearer_token and bearer_token != "none":
        # Static bearer token
        token = bearer_token

    # Build request
    url = f"{host.rstrip('/')}{base_path}{path}"
    req_headers = {"Content-Type": "application/json"}

    if token:
        req_headers["Authorization"] = f"Bearer {token}"

    if headers_json:
        try:
            extra_headers = json.loads(headers_json)
            req_headers.update(extra_headers)
        except json.JSONDecodeError:
            pass

    body_data = None
    if body:
        try:
            body_data = json.loads(body)
        except json.JSONDecodeError:
            body_data = body

    # Make the request
    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            json=body_data if isinstance(body_data, dict) else None,
            data=body_data if isinstance(body_data, str) else None,
            headers=req_headers,
            timeout=30
        )

        # Parse response
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                response_body = response.json()
            except json.JSONDecodeError:
                response_body = response.text
        else:
            response_body = response.text

        return json.dumps({
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response_body
        })

    except requests.Timeout:
        return json.dumps({"error": "Request timed out"})
    except requests.RequestException as e:
        return json.dumps({"error": str(e)})
'''


class ExternalAPIFunction:
    """
    UC Function definition for calling external APIs.

    This class provides:
    - The function code as a string
    - SQL generation for registration
    - Metadata for discovery
    """

    name = "call_external_api"
    description = "Call external APIs using UC Connection credentials (OAuth M2M or static token)"
    code = EXTERNAL_API_FUNCTION_CODE

    @classmethod
    def get_registration_sql(cls, catalog: str, schema: str) -> str:
        """
        Generate SQL to register this function in Unity Catalog.

        Args:
            catalog: Target catalog name
            schema: Target schema name

        Returns:
            SQL statement to create the function
        """
        return f"""
CREATE OR REPLACE FUNCTION {catalog}.{schema}.{cls.name}(
    connection_name STRING COMMENT 'Name of the UC HTTP Connection',
    method STRING COMMENT 'HTTP method (GET, POST, PUT, DELETE)',
    path STRING COMMENT 'API path to call',
    body STRING DEFAULT NULL COMMENT 'Request body as JSON string',
    headers_json STRING DEFAULT NULL COMMENT 'Additional headers as JSON string'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: {cls.description}'
AS $$
{cls.code}

return call_external_api(connection_name, method, path, body, headers_json)
$$;
"""

    @classmethod
    def get_mcp_endpoint(cls, workspace_url: str, catalog: str, schema: str) -> str:
        """Get the MCP endpoint for this function."""
        return f"{workspace_url}/api/2.0/mcp/functions/{catalog}/{schema}/{cls.name}"

    @classmethod
    def get_connection_sql_example(cls) -> str:
        """Get example SQL for creating a UC Connection."""
        return """
-- Example: Create UC Connection for ServiceNow
CREATE CONNECTION servicenow_api TYPE HTTP
OPTIONS (
    host 'https://your-instance.service-now.com',
    base_path '/api/now',
    bearer_token 'oauth',
    client_id '{{secrets/servicenow/client_id}}',
    client_secret '{{secrets/servicenow/client_secret}}',
    token_endpoint 'https://your-instance.service-now.com/oauth_token.do',
    oauth_scope 'useraccount'
);

-- Grant access
GRANT USE CONNECTION servicenow_api TO `it-helpdesk`;
"""
