"""
MCP (Model Context Protocol) integration for Unity Catalog.

This package provides:
- UC Functions that become MCP tools via Databricks managed MCP servers
- Clients for calling MCP endpoints
"""
from . import functions

__all__ = ["functions"]
