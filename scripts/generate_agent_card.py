#!/usr/bin/env python3
"""
Generate an A2A-compliant agent card from a Unity Catalog connection.

This script reads a UC HTTP connection and generates an agent card that
conforms to the A2A Protocol Specification:
https://a2a-protocol.org/latest/specification/

Usage:
    python generate_agent_card.py --name echo
    python generate_agent_card.py --name echo --output echo-agent.json

Requirements:
    - databricks-sdk
    - DATABRICKS_HOST and authentication configured
"""

import argparse
import json
import sys
from typing import Optional
from databricks.sdk import WorkspaceClient


def get_connection(agent_name: str) -> dict:
    """
    Get UC connection for an agent.

    Args:
        agent_name: Name of the agent (without -a2a suffix)

    Returns:
        Connection info object
    """
    w = WorkspaceClient()
    connection_name = f"{agent_name}-a2a"

    conn = w.connections.get(connection_name)
    return conn


def generate_agent_card(agent_name: str, gateway_url: Optional[str] = None) -> dict:
    """
    Generate an A2A-compliant agent card from UC connection.

    Per A2A Protocol Specification (sections 4.4, 4.5):
    https://a2a-protocol.org/latest/specification/

    Args:
        agent_name: Name of the agent
        gateway_url: Optional gateway URL (if proxying through APIM)

    Returns:
        A2A Agent Card dict
    """
    # Get the UC connection
    conn = get_connection(agent_name)
    options = conn.options or {}

    # Build endpoint URL
    host = options.get("host", "").rstrip("/")
    base_path = options.get("base_path", "")

    # If gateway URL provided, use that; otherwise use direct backend URL
    if gateway_url:
        agent_url = f"{gateway_url.rstrip('/')}/agents/{agent_name}"
    else:
        agent_url = f"{host}{base_path}"

    # Determine auth description
    bearer_token = options.get("bearer_token", "").lower()
    if bearer_token == "databricks":
        auth_description = "Databricks OAuth token (same tenant passthrough)"
        bearer_format = "Databricks-JWT"
    else:
        auth_description = "Bearer token"
        bearer_format = "JWT"

    # Generate A2A-compliant agent card
    # Per A2A spec sections 4.4 (AgentCard) and 4.5 (SecurityScheme)
    agent_card = {
        # Required fields
        "name": agent_name,
        "url": agent_url,

        # Recommended fields
        "description": conn.comment or f"A2A Agent: {agent_name}",
        "version": "1.0.0",

        # Provider information
        "provider": {
            "organization": conn.owner or "Unknown",
        },

        # Security schemes (per A2A spec section 4.5)
        # HTTPAuthSecurityScheme with bearer scheme
        "securitySchemes": {
            "bearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": bearer_format,
                "description": auth_description
            }
        },

        # Security requirements - which schemes are required
        "security": [
            {"bearer": []}
        ],

        # Capabilities
        "capabilities": {
            "streaming": True,
            "pushNotifications": False
        },

        # Input/Output modes
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],

        # Custom extension: UC connection metadata
        "_ucConnection": {
            "name": conn.name,
            "fullName": conn.full_name,
            "backendHost": host,
            "backendPath": base_path
        }
    }

    return agent_card


def print_agent_card(card: dict, format: str = "json"):
    """Print agent card in specified format."""
    if format == "json":
        print(json.dumps(card, indent=2))
    elif format == "yaml":
        try:
            import yaml
            print(yaml.dump(card, default_flow_style=False))
        except ImportError:
            print("PyYAML not installed, using JSON format")
            print(json.dumps(card, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Generate A2A agent card from UC connection"
    )
    parser.add_argument(
        "--name", "-n",
        required=True,
        help="Agent name (connection should be named {name}-a2a)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: print to stdout)"
    )
    parser.add_argument(
        "--gateway-url", "-g",
        help="APIM gateway URL (if proxying through gateway)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "yaml"],
        default="json",
        help="Output format (default: json)"
    )

    args = parser.parse_args()

    try:
        card = generate_agent_card(args.name, args.gateway_url)

        if args.output:
            with open(args.output, "w") as f:
                json.dump(card, f, indent=2)
            print(f"Agent card saved to: {args.output}", file=sys.stderr)
        else:
            print_agent_card(card, args.format)

    except Exception as e:
        print(f"Error generating agent card: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
