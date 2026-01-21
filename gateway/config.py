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

    class Config:
        env_prefix = ""
        case_sensitive = False


settings = Settings()
