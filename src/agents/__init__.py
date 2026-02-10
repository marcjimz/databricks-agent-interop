"""
Agents for Databricks Agent Interoperability Framework.

- databricks: Databricks agents using UC Functions as MCP tools
- foundry: Azure AI Foundry MCP integration
"""
from .databricks import DatabricksMCPAgent
from .foundry import FoundryMCPClient, FoundryAgentClient

__all__ = [
    "DatabricksMCPAgent",
    "FoundryMCPClient",
    "FoundryAgentClient",
]
