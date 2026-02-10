"""
Setup OAuth2 Connection for Databricks MCP in Azure AI Foundry.

This script sets up proper OAuth authentication between Azure AI Foundry and
Databricks MCP servers, following the official documentation:
https://learn.microsoft.com/en-us/azure/databricks/generative-ai/mcp/connect-external-services

The OAuth flow requires:
1. Create a Databricks OAuth app (custom app integration) in the account console
2. Create an OAuth2 connection in Azure AI Foundry with the OAuth app credentials
3. Add the Foundry redirect URL to the Databricks OAuth app
4. User provides consent when first using the MCP tools

Usage:
    python setup_oauth_connection.py --create     # Create OAuth app and connection
    python setup_oauth_connection.py --status     # Check current status
    python setup_oauth_connection.py --delete     # Delete OAuth app and connection

Environment Variables (from .env):
    DATABRICKS_HOST         - Databricks workspace URL
    DATABRICKS_ACCOUNT_ID   - Databricks account ID (for OAuth app creation)
    SUBSCRIPTION_ID         - Azure subscription ID
    RESOURCE_GROUP          - Azure resource group
    PREFIX                  - Resource prefix
    UC_CATALOG              - Unity Catalog catalog name
    UC_SCHEMA               - Unity Catalog schema name
"""

import argparse
import json
import os
import sys
import subprocess

# Add parent dir for .env
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env():
    """Load environment variables from .env file."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
        print(f"[OK] Loaded .env from {env_path}")
    else:
        print(f"[WARN] No .env file at {env_path}")


def get_config():
    """Get configuration from environment."""
    load_env()

    required = ["DATABRICKS_HOST", "SUBSCRIPTION_ID", "RESOURCE_GROUP"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    databricks_host = os.environ["DATABRICKS_HOST"].rstrip("/")
    catalog = os.environ.get("UC_CATALOG", "mcp_agents")
    schema = os.environ.get("UC_SCHEMA", "tools")
    prefix = os.environ.get("PREFIX", "mcpagent01")

    return {
        "databricks_host": databricks_host,
        "account_id": os.environ.get("DATABRICKS_ACCOUNT_ID"),
        "subscription_id": os.environ["SUBSCRIPTION_ID"],
        "resource_group": os.environ["RESOURCE_GROUP"],
        "project_name": f"proj-{prefix}",
        "catalog": catalog,
        "schema": schema,
        "mcp_server_url": f"{databricks_host}/api/2.0/mcp/functions/{catalog}/{schema}",
        "oauth_app_name": "foundry-mcp-oauth",
        "connection_name": "databricks-oauth",
        # Databricks OIDC endpoints
        "auth_url": f"{databricks_host}/oidc/v1/authorize",
        "token_url": f"{databricks_host}/oidc/v1/token",
    }


def run_command(cmd, capture=True):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=capture, text=True
        )
        if result.returncode != 0 and capture:
            print(f"[WARN] Command failed: {result.stderr}")
        return result.stdout.strip() if capture else None
    except Exception as e:
        print(f"[ERROR] Command failed: {e}")
        return None


def get_azure_token():
    """Get Azure Management API token."""
    token = run_command(
        "az account get-access-token --resource https://management.azure.com/ --query accessToken -o tsv"
    )
    if not token:
        print("[ERROR] Failed to get Azure token. Run: az login")
        sys.exit(1)
    return token


def get_databricks_token():
    """Get Databricks token via Azure CLI."""
    token = run_command(
        "az account get-access-token --resource 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d --query accessToken -o tsv"
    )
    if not token:
        print("[ERROR] Failed to get Databricks token. Run: az login")
        sys.exit(1)
    return token


def list_oauth_apps(config):
    """List existing Databricks OAuth apps."""
    print("\n=== Checking Existing Databricks OAuth Apps ===")

    # Use Databricks CLI to list custom app integrations
    result = run_command("databricks account custom-app-integration list --output json 2>/dev/null")

    if result:
        try:
            apps = json.loads(result)
            print(f"Found {len(apps)} OAuth apps:")
            for app in apps:
                print(f"  - {app.get('name', 'unnamed')}: {app.get('integration_id', 'N/A')}")
                print(f"    Client ID: {app.get('client_id', 'N/A')}")
            return apps
        except json.JSONDecodeError:
            print(f"[WARN] Could not parse OAuth apps: {result}")
    else:
        print("[INFO] No OAuth apps found or unable to list (may need account admin access)")

    return []


def create_databricks_oauth_app(config, redirect_urls=None):
    """Create a Databricks OAuth app for Foundry."""
    print("\n=== Creating Databricks OAuth App ===")

    if not redirect_urls:
        # Use placeholder redirect URLs - will update later with actual Foundry URL
        redirect_urls = [
            "https://ai.azure.com/oauth/callback",
            "https://management.azure.com/oauth/callback",
        ]

    app_config = {
        "name": config["oauth_app_name"],
        "redirect_urls": redirect_urls,
        "confidential": True,  # Generate client secret
        "scopes": ["all-apis"],
        "token_access_policy": {
            "access_token_ttl_in_minutes": 60,
            "refresh_token_ttl_in_minutes": 10080  # 7 days
        }
    }

    print(f"Creating OAuth app: {config['oauth_app_name']}")
    print(f"Redirect URLs: {redirect_urls}")
    print(f"Scopes: all-apis")

    # Try using Databricks CLI
    cmd = f"databricks account custom-app-integration create --json '{json.dumps(app_config)}'"
    result = run_command(cmd)

    if result:
        try:
            app = json.loads(result)
            print(f"\n[OK] OAuth app created successfully!")
            print(f"  Integration ID: {app.get('integration_id')}")
            print(f"  Client ID: {app.get('client_id')}")
            if app.get('client_secret'):
                print(f"  Client Secret: {app.get('client_secret')}")
                print("\n  [!] SAVE THE CLIENT SECRET - it won't be shown again!")
            return app
        except json.JSONDecodeError:
            print(f"[INFO] Result: {result}")
    else:
        print("[WARN] Could not create OAuth app via CLI")
        print("")
        print("Please create the OAuth app manually:")
        print("1. Go to Databricks Account Console")
        print("2. Navigate to Settings > App Connections > Add connection")
        print(f"3. Name: {config['oauth_app_name']}")
        print(f"4. Redirect URLs: {redirect_urls}")
        print("5. Check 'Generate a client secret'")
        print("6. Scopes: all-apis")
        print("")

        # Prompt for manual entry
        client_id = input("Enter the Client ID from the OAuth app: ").strip()
        client_secret = input("Enter the Client Secret: ").strip()

        if client_id and client_secret:
            return {
                "client_id": client_id,
                "client_secret": client_secret,
                "name": config["oauth_app_name"]
            }

    return None


def create_foundry_oauth_connection(config, client_id, client_secret):
    """Create OAuth2 connection in Azure AI Foundry."""
    print("\n=== Creating Azure AI Foundry OAuth2 Connection ===")

    token = get_azure_token()

    # OAuth2 connection payload
    connection_payload = {
        "properties": {
            "authType": "OAuth2",
            "category": "RemoteTool",
            "target": config["mcp_server_url"],
            "credentials": {
                "clientId": client_id,
                "clientSecret": client_secret,
            },
            "metadata": {
                "authorizationUrl": config["auth_url"],
                "tokenUrl": config["token_url"],
                "refreshUrl": config["token_url"],
                "scope": "all-apis",
            }
        }
    }

    print(f"Connection name: {config['connection_name']}")
    print(f"Target: {config['mcp_server_url']}")
    print(f"Auth URL: {config['auth_url']}")
    print(f"Token URL: {config['token_url']}")

    # Create connection via ARM API
    import requests

    url = (
        f"https://management.azure.com/subscriptions/{config['subscription_id']}"
        f"/resourceGroups/{config['resource_group']}"
        f"/providers/Microsoft.MachineLearningServices/workspaces/{config['project_name']}"
        f"/connections/{config['connection_name']}?api-version=2024-04-01-preview"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print(f"\nSending request to: {url}")

    resp = requests.put(url, headers=headers, json=connection_payload)

    if resp.status_code in [200, 201]:
        result = resp.json()
        print(f"\n[OK] Connection created successfully!")

        # Check for redirect URL in response
        props = result.get("properties", {})
        if "redirectUrl" in props:
            print(f"\n[!] REDIRECT URL: {props['redirectUrl']}")
            print("    Add this URL to your Databricks OAuth app!")

        return result
    else:
        print(f"[ERROR] Failed to create connection: {resp.status_code}")
        print(f"Response: {resp.text}")
        return None


def get_connection_status(config):
    """Get status of the OAuth connection."""
    print("\n=== Checking Connection Status ===")

    token = get_azure_token()

    import requests

    url = (
        f"https://management.azure.com/subscriptions/{config['subscription_id']}"
        f"/resourceGroups/{config['resource_group']}"
        f"/providers/Microsoft.MachineLearningServices/workspaces/{config['project_name']}"
        f"/connections/{config['connection_name']}?api-version=2024-04-01-preview"
    )

    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.get(url, headers=headers)

    if resp.status_code == 200:
        result = resp.json()
        props = result.get("properties", {})
        print(f"Connection: {config['connection_name']}")
        print(f"  Auth Type: {props.get('authType')}")
        print(f"  Category: {props.get('category')}")
        print(f"  Target: {props.get('target')}")

        metadata = props.get("metadata", {})
        if metadata:
            print(f"  Auth URL: {metadata.get('authorizationUrl')}")
            print(f"  Token URL: {metadata.get('tokenUrl')}")
            print(f"  Scope: {metadata.get('scope')}")

        if props.get("redirectUrl"):
            print(f"\n  [!] Redirect URL: {props.get('redirectUrl')}")

        return result
    elif resp.status_code == 404:
        print(f"Connection '{config['connection_name']}' not found")
        return None
    else:
        print(f"[ERROR] Failed to get connection: {resp.status_code}")
        print(f"Response: {resp.text}")
        return None


def delete_connection(config):
    """Delete the OAuth connection."""
    print("\n=== Deleting OAuth Connection ===")

    token = get_azure_token()

    import requests

    url = (
        f"https://management.azure.com/subscriptions/{config['subscription_id']}"
        f"/resourceGroups/{config['resource_group']}"
        f"/providers/Microsoft.MachineLearningServices/workspaces/{config['project_name']}"
        f"/connections/{config['connection_name']}?api-version=2024-04-01-preview"
    )

    headers = {"Authorization": f"Bearer {token}"}

    resp = requests.delete(url, headers=headers)

    if resp.status_code in [200, 204]:
        print(f"[OK] Connection '{config['connection_name']}' deleted")
        return True
    elif resp.status_code == 404:
        print(f"Connection '{config['connection_name']}' not found")
        return True
    else:
        print(f"[ERROR] Failed to delete connection: {resp.status_code}")
        print(f"Response: {resp.text}")
        return False


def update_databricks_oauth_app(config, integration_id, redirect_url):
    """Update Databricks OAuth app with Foundry redirect URL."""
    print("\n=== Updating Databricks OAuth App with Redirect URL ===")

    update_config = {
        "redirect_urls": [redirect_url]
    }

    cmd = f"databricks account custom-app-integration update {integration_id} --json '{json.dumps(update_config)}'"
    result = run_command(cmd)

    if result:
        print(f"[OK] OAuth app updated with redirect URL: {redirect_url}")
        return True
    else:
        print(f"[WARN] Could not update OAuth app via CLI")
        print("")
        print("Please update the OAuth app manually:")
        print(f"1. Go to Databricks Account Console")
        print(f"2. Navigate to Settings > App Connections")
        print(f"3. Find app: {config['oauth_app_name']}")
        print(f"4. Add redirect URL: {redirect_url}")
        return False


def create_full_oauth_setup(config):
    """Create complete OAuth setup."""
    print("=" * 60)
    print("Setting up OAuth2 for Databricks MCP in Azure AI Foundry")
    print("=" * 60)

    print(f"\nConfiguration:")
    print(f"  Databricks Host: {config['databricks_host']}")
    print(f"  MCP Server URL: {config['mcp_server_url']}")
    print(f"  Foundry Project: {config['project_name']}")
    print(f"  Connection Name: {config['connection_name']}")

    # Step 1: Check/Create Databricks OAuth app
    apps = list_oauth_apps(config)
    existing_app = next((a for a in apps if a.get("name") == config["oauth_app_name"]), None)

    if existing_app:
        print(f"\n[INFO] OAuth app '{config['oauth_app_name']}' already exists")
        client_id = existing_app.get("client_id")
        client_secret = input("Enter the Client Secret (or press Enter to create new app): ").strip()
        if not client_secret:
            # Delete and recreate
            print("Creating new OAuth app...")
            oauth_app = create_databricks_oauth_app(config)
        else:
            oauth_app = {"client_id": client_id, "client_secret": client_secret}
    else:
        oauth_app = create_databricks_oauth_app(config)

    if not oauth_app:
        print("[ERROR] Could not create/get OAuth app credentials")
        return False

    client_id = oauth_app.get("client_id")
    client_secret = oauth_app.get("client_secret")

    if not client_id or not client_secret:
        print("[ERROR] Missing client_id or client_secret")
        return False

    # Step 2: Create Foundry connection
    result = create_foundry_oauth_connection(config, client_id, client_secret)

    if not result:
        print("[ERROR] Could not create Foundry connection")
        return False

    # Step 3: Get and update redirect URL
    redirect_url = result.get("properties", {}).get("redirectUrl")
    if redirect_url and oauth_app.get("integration_id"):
        update_databricks_oauth_app(config, oauth_app["integration_id"], redirect_url)
    elif redirect_url:
        print(f"\n[!] IMPORTANT: Add this redirect URL to your Databricks OAuth app:")
        print(f"    {redirect_url}")

    print("\n" + "=" * 60)
    print("OAuth Setup Complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Verify the redirect URL is added to the Databricks OAuth app")
    print("2. Run the test script: python test_mcp_debug.py")
    print("3. When prompted, complete the OAuth consent flow in your browser")
    print(f"4. Update MCP_PROJECT_CONNECTION_NAME in .env to: {config['connection_name']}")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Setup OAuth2 Connection for Databricks MCP in Azure AI Foundry"
    )
    parser.add_argument("--create", action="store_true", help="Create OAuth app and connection")
    parser.add_argument("--status", action="store_true", help="Check current status")
    parser.add_argument("--delete", action="store_true", help="Delete OAuth connection")
    parser.add_argument("--list-apps", action="store_true", help="List Databricks OAuth apps")

    args = parser.parse_args()

    if not any([args.create, args.status, args.delete, args.list_apps]):
        parser.print_help()
        return

    config = get_config()

    if args.list_apps:
        list_oauth_apps(config)
    elif args.status:
        get_connection_status(config)
    elif args.delete:
        delete_connection(config)
    elif args.create:
        create_full_oauth_setup(config)


if __name__ == "__main__":
    main()
