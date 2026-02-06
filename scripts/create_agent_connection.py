#!/usr/bin/env python3
"""
Create an A2A agent connection in Unity Catalog.

This script creates an HTTP connection in Unity Catalog that represents
an A2A agent. The connection stores the agent's endpoint URL and auth
configuration.

Usage:
    python create_agent_connection.py --name echo --host https://echo-agent.azurewebsites.net

Requirements:
    - databricks-sdk
    - DATABRICKS_HOST and authentication configured
"""

import argparse
import sys
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import ConnectionType


def create_a2a_connection(
    agent_name: str,
    host: str,
    base_path: str = "/a2a",
    bearer_token: str = "databricks",
    comment: str = None,
    port: str = "443"
) -> dict:
    """
    Create a Unity Catalog HTTP connection for an A2A agent.

    Connection name format: {agent_name}-a2a

    Args:
        agent_name: Name of the agent
        host: Agent backend URL (e.g., https://echo-agent.azurewebsites.net)
        base_path: Agent endpoint path (default: /a2a)
        bearer_token: Auth token or 'databricks' for passthrough
        comment: Description of the agent
        port: Port number (default: 443)

    Returns:
        ConnectionInfo object with connection details
    """
    w = WorkspaceClient()

    connection_name = f"{agent_name}-a2a"

    # Build options dict
    options = {
        "host": host,
        "port": port,
        "base_path": base_path,
    }

    # Only add bearer_token if specified
    if bearer_token:
        options["bearer_token"] = bearer_token

    # Create the HTTP connection
    conn = w.connections.create(
        name=connection_name,
        connection_type=ConnectionType.HTTP,
        options=options,
        comment=comment or f"A2A Agent: {agent_name}"
    )

    return conn


def main():
    parser = argparse.ArgumentParser(
        description="Create an A2A agent connection in Unity Catalog"
    )
    parser.add_argument(
        "--name", "-n",
        required=True,
        help="Agent name (connection will be named {name}-a2a)"
    )
    parser.add_argument(
        "--host", "-H",
        required=True,
        help="Agent backend URL (e.g., https://echo-agent.azurewebsites.net)"
    )
    parser.add_argument(
        "--base-path", "-p",
        default="/a2a",
        help="Agent endpoint path (default: /a2a)"
    )
    parser.add_argument(
        "--bearer-token", "-t",
        default="databricks",
        help="Bearer token or 'databricks' for passthrough (default: databricks)"
    )
    parser.add_argument(
        "--comment", "-c",
        help="Description of the agent"
    )
    parser.add_argument(
        "--port",
        default="443",
        help="Port number (default: 443)"
    )

    args = parser.parse_args()

    try:
        conn = create_a2a_connection(
            agent_name=args.name,
            host=args.host,
            base_path=args.base_path,
            bearer_token=args.bearer_token,
            comment=args.comment,
            port=args.port
        )

        print(f"Successfully created connection:")
        print(f"  Name: {conn.name}")
        print(f"  Full name: {conn.full_name}")
        print(f"  Owner: {conn.owner}")
        print(f"  Type: {conn.connection_type}")
        print(f"  Comment: {conn.comment}")
        print()
        print("Options:")
        for key, value in (conn.options or {}).items():
            # Mask sensitive values
            if "token" in key.lower() or "secret" in key.lower():
                value = "***"
            print(f"  {key}: {value}")

        print()
        print("To grant access to users:")
        print(f"  GRANT USE CONNECTION ON CONNECTION {conn.name} TO `user@example.com`;")

    except Exception as e:
        print(f"Error creating connection: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
