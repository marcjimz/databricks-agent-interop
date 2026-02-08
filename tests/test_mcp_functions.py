"""Tests for MCP function definitions."""
import pytest


class TestFunctionRegistry:
    """Test the UC Function registry."""

    def test_registry_import(self):
        """Registry can be imported."""
        from src.mcp.functions import FunctionRegistry
        assert FunctionRegistry is not None

    def test_registry_list_functions(self):
        """Registry lists all functions."""
        from src.mcp.functions import FunctionRegistry

        registry = FunctionRegistry(catalog="test_catalog", schema="test_schema")
        functions = registry.list_functions()

        assert len(functions) >= 3
        names = [f["name"] for f in functions]
        assert "echo" in names
        assert "call_foundry_agent" in names
        assert "call_external_api" in names

    def test_registry_generates_sql(self):
        """Registry generates valid SQL."""
        from src.mcp.functions import FunctionRegistry

        registry = FunctionRegistry(catalog="mcp_agents", schema="tools")
        sql = registry.get_all_functions_sql()

        assert "CREATE CATALOG IF NOT EXISTS mcp_agents" in sql
        assert "CREATE SCHEMA IF NOT EXISTS mcp_agents.tools" in sql
        assert "CREATE OR REPLACE FUNCTION" in sql

    def test_echo_function_sql(self):
        """Echo function generates valid SQL."""
        from src.mcp.functions import EchoFunction

        sql = EchoFunction.get_registration_sql("mcp_agents", "tools")

        assert "CREATE OR REPLACE FUNCTION mcp_agents.tools.echo" in sql
        assert "message STRING" in sql
        assert "RETURNS STRING" in sql
        assert "LANGUAGE PYTHON" in sql

    def test_foundry_function_sql(self):
        """Foundry agent function generates valid SQL."""
        from src.mcp.functions import FoundryAgentFunction

        sql = FoundryAgentFunction.get_registration_sql("mcp_agents", "tools")

        assert "CREATE OR REPLACE FUNCTION mcp_agents.tools.call_foundry_agent" in sql
        assert "agent_name STRING" in sql
        assert "message STRING" in sql

    def test_external_api_function_sql(self):
        """External API function generates valid SQL."""
        from src.mcp.functions import ExternalAPIFunction

        sql = ExternalAPIFunction.get_registration_sql("mcp_agents", "tools")

        assert "CREATE OR REPLACE FUNCTION mcp_agents.tools.call_external_api" in sql
        assert "connection_name STRING" in sql
        assert "method STRING" in sql

    def test_calculator_function_sql(self):
        """Calculator function generates valid SQL."""
        from src.mcp.functions import CalculatorFunction

        sql = CalculatorFunction.get_registration_sql("mcp_agents", "tools")

        assert "CREATE OR REPLACE FUNCTION mcp_agents.tools.calculator" in sql
        assert "expression STRING" in sql
        assert "RETURNS STRING" in sql

    def test_mcp_endpoints(self):
        """Registry generates correct MCP endpoints."""
        from src.mcp.functions import FunctionRegistry

        registry = FunctionRegistry(catalog="mcp_agents", schema="tools")
        endpoints = registry.get_mcp_endpoints("https://workspace.azuredatabricks.net")

        assert "echo" in endpoints
        assert "calculator" in endpoints
        assert "call_foundry_agent" in endpoints
        assert "workspace.azuredatabricks.net/api/2.0/mcp/functions" in endpoints["echo"]
