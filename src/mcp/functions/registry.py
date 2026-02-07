"""
UC Function Registry

Central registry for all MCP tool functions.
Provides SQL generation and registration utilities.
"""
from typing import List, Type

from .foundry import FoundryAgentFunction
from .external_api import ExternalAPIFunction


# Echo function code (simple test function)
ECHO_FUNCTION_CODE = '''
import json
from datetime import datetime

def echo(message: str) -> str:
    """Echo back the input message with metadata."""
    return json.dumps({
        "echo": message,
        "timestamp": datetime.now().isoformat(),
        "source": "UC Function via Databricks Managed MCP"
    })
'''

# Calculator function code
CALCULATOR_FUNCTION_CODE = '''
import json
import re
from datetime import datetime

def calculator(expression: str) -> str:
    """Evaluate a mathematical expression safely."""
    try:
        # Only allow safe characters: digits, operators, parentheses, decimals, spaces
        if not re.match(r'^[0-9+\-*/().\\s]+$', expression):
            return json.dumps({
                "error": "Invalid expression. Only numbers and operators (+, -, *, /, parentheses) allowed.",
                "expression": expression
            })

        # Evaluate the expression
        result = eval(expression)

        return json.dumps({
            "expression": expression,
            "result": result,
            "timestamp": datetime.now().isoformat(),
            "source": "UC Function via Databricks Managed MCP"
        })
    except Exception as e:
        return json.dumps({
            "error": str(e),
            "expression": expression
        })
'''


class EchoFunction:
    """Simple echo function for testing MCP connectivity."""

    name = "echo"
    description = "Echo back the input message. Use for testing MCP connectivity."
    code = ECHO_FUNCTION_CODE

    @classmethod
    def get_registration_sql(cls, catalog: str, schema: str) -> str:
        return f"""
CREATE OR REPLACE FUNCTION {catalog}.{schema}.{cls.name}(
    message STRING COMMENT 'Message to echo back'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: {cls.description}'
AS $$
{cls.code}

return echo(message)
$$;
"""

    @classmethod
    def get_mcp_endpoint(cls, workspace_url: str, catalog: str, schema: str) -> str:
        return f"{workspace_url}/api/2.0/mcp/functions/{catalog}/{schema}/{cls.name}"


class CalculatorFunction:
    """Calculator function for evaluating mathematical expressions."""

    name = "calculator"
    description = "Evaluate mathematical expressions. Supports +, -, *, /, and parentheses."
    code = CALCULATOR_FUNCTION_CODE

    @classmethod
    def get_registration_sql(cls, catalog: str, schema: str) -> str:
        return f"""
CREATE OR REPLACE FUNCTION {catalog}.{schema}.{cls.name}(
    expression STRING COMMENT 'Mathematical expression to evaluate (e.g., "2 + 2", "10 * 5")'
)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'MCP Tool: {cls.description}'
AS $$
{cls.code}

return calculator(expression)
$$;
"""

    @classmethod
    def get_mcp_endpoint(cls, workspace_url: str, catalog: str, schema: str) -> str:
        return f"{workspace_url}/api/2.0/mcp/functions/{catalog}/{schema}/{cls.name}"


class FunctionRegistry:
    """
    Registry of all UC Functions for MCP tools.

    Provides:
    - List of all available functions
    - SQL generation for registration
    - Catalog/schema setup
    """

    # All registered function classes
    FUNCTIONS: List[Type] = [
        EchoFunction,
        CalculatorFunction,
        FoundryAgentFunction,
        ExternalAPIFunction,
    ]

    def __init__(self, catalog: str = "mcp_agents", schema: str = "tools"):
        """
        Initialize the registry.

        Args:
            catalog: Target UC catalog
            schema: Target UC schema
        """
        self.catalog = catalog
        self.schema = schema

    def get_setup_sql(self) -> str:
        """
        Generate SQL to set up the catalog and schema.

        Returns:
            SQL statements
        """
        return f"""
-- Create catalog and schema for MCP tools
CREATE CATALOG IF NOT EXISTS {self.catalog};
CREATE SCHEMA IF NOT EXISTS {self.catalog}.{self.schema};

-- Grant usage (customize as needed)
-- GRANT USE CATALOG ON CATALOG {self.catalog} TO `users`;
-- GRANT USE SCHEMA ON SCHEMA {self.catalog}.{self.schema} TO `users`;
"""

    def get_function_sql(self, function_class: Type) -> str:
        """
        Get registration SQL for a specific function.

        Args:
            function_class: Function class (e.g., FoundryAgentFunction)

        Returns:
            SQL statement
        """
        return function_class.get_registration_sql(self.catalog, self.schema)

    def get_all_functions_sql(self) -> str:
        """
        Generate SQL to register all functions.

        Returns:
            SQL statements for all functions
        """
        parts = [self.get_setup_sql()]

        for func_class in self.FUNCTIONS:
            parts.append(f"\n-- {func_class.name}: {func_class.description}")
            parts.append(self.get_function_sql(func_class))

        return "\n".join(parts)

    def get_grant_sql(self, principal: str = "users") -> str:
        """
        Generate SQL to grant EXECUTE on all functions.

        Args:
            principal: User, group, or service principal to grant to

        Returns:
            SQL statements
        """
        grants = []
        for func_class in self.FUNCTIONS:
            grants.append(
                f"GRANT EXECUTE ON FUNCTION {self.catalog}.{self.schema}.{func_class.name} "
                f"TO `{principal}`;"
            )
        return "\n".join(grants)

    def get_mcp_endpoints(self, workspace_url: str) -> dict:
        """
        Get MCP endpoints for all functions.

        Args:
            workspace_url: Databricks workspace URL

        Returns:
            Dict mapping function name to endpoint URL
        """
        return {
            func.name: func.get_mcp_endpoint(workspace_url, self.catalog, self.schema)
            for func in self.FUNCTIONS
        }

    def list_functions(self) -> List[dict]:
        """
        List all registered functions with metadata.

        Returns:
            List of function info dicts
        """
        return [
            {
                "name": func.name,
                "full_name": f"{self.catalog}.{self.schema}.{func.name}",
                "description": func.description,
            }
            for func in self.FUNCTIONS
        ]

    def print_registration_sql(self):
        """Print all registration SQL to stdout."""
        print(self.get_all_functions_sql())

    @classmethod
    def register_all(cls, catalog: str = "mcp_agents", schema: str = "tools"):
        """
        Convenience method to get all registration SQL.

        Args:
            catalog: Target catalog
            schema: Target schema

        Returns:
            Complete SQL for registration
        """
        registry = cls(catalog, schema)
        return registry.get_all_functions_sql()


def generate_registration_sql(catalog: str = "mcp_agents", schema: str = "tools") -> str:
    """
    Generate complete SQL for registering all MCP functions.

    This is the main entry point for generating registration SQL.

    Args:
        catalog: Target UC catalog
        schema: Target UC schema

    Returns:
        SQL statements to run in Databricks
    """
    return FunctionRegistry.register_all(catalog, schema)


if __name__ == "__main__":
    # Print registration SQL when run directly
    print(generate_registration_sql())
