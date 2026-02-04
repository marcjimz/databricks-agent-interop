"""Configuration settings for the A2A Gateway."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "A2A Gateway"
    app_version: str = "0.1.0"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Databricks
    databricks_host: str = ""
    databricks_token: str = ""

    # Unity Catalog - for agent discovery
    catalog_name: str = "main"
    schema_name: str = "default"

    # A2A Connection suffix for discovery
    a2a_connection_suffix: str = "-a2a"

    # Tracing (Experimental)
    tracing_enabled: bool = False
    mlflow_experiment_name: str = "/Shared/a2a-gateway-traces"
    trace_uc_schema: str | None = None  # e.g., "catalog.schema" for Delta table storage
    trace_sql_warehouse_id: str | None = None  # SQL warehouse for monitoring queries
    gateway_environment: str = "dev"
    gateway_instance_id: str | None = None  # Auto-generated if not provided

    class Config:
        env_prefix = ""
        case_sensitive = False


settings = Settings()
