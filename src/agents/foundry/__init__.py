"""
Azure AI Foundry agent wrappers.

These provide interfaces for calling Foundry agents from Databricks
and for Foundry agents to call Databricks MCP.
"""
from .client import FoundryAgentClient
from .mcp_client import FoundryMCPClient

__all__ = ["FoundryAgentClient", "FoundryMCPClient"]
