"""
UC Functions for MCP Tools.

These functions are registered in Unity Catalog and automatically exposed
as MCP tools via Databricks managed MCP servers.

Pattern:
    MCP Client → Databricks Managed MCP → UC Function → External Service

Usage:
    from src.mcp.functions import FunctionRegistry

    # Generate all registration SQL
    registry = FunctionRegistry(catalog="mcp_agents", schema="tools")
    print(registry.get_all_functions_sql())

    # Or generate for individual functions
    from src.mcp.functions import FoundryAgentFunction
    print(FoundryAgentFunction.get_registration_sql("mcp_agents", "tools"))
"""
from .foundry import FoundryAgentFunction
from .external_api import ExternalAPIFunction
from .registry import EchoFunction, CalculatorFunction, FunctionRegistry, generate_registration_sql

__all__ = [
    "FoundryAgentFunction",
    "ExternalAPIFunction",
    "EchoFunction",
    "CalculatorFunction",
    "FunctionRegistry",
    "generate_registration_sql",
]
