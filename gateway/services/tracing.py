"""MLflow tracing utilities for A2A Gateway.

This module provides tracing configuration, setup, and utilities
for logging traces to MLflow and optionally to Unity Catalog Delta tables.

Experimental Feature: MLflow tracing requires mlflow>=2.19.0. UC schema
storage uses mlflow.tracing.set_destination() with UCSchemaLocation.
"""

import os
import uuid
import logging
from dataclasses import dataclass
from contextlib import contextmanager
from typing import Generator

from models.trace import (
    GatewayTags,
    UserTags,
    AgentTags,
    RequestTags,
    TraceTags,
)

logger = logging.getLogger(__name__)

# Singleton instance
_tracer_instance: "GatewayTracer | None" = None


@dataclass
class TracingConfig:
    """Configuration for MLflow tracing.

    Attributes:
        enabled: Whether tracing is enabled.
        experiment_name: MLflow experiment name/path.
        uc_schema: Unity Catalog schema for Delta table storage (e.g., "catalog.schema").
        sql_warehouse_id: SQL warehouse ID for monitoring queries.
        gateway_version: Gateway version string.
        gateway_environment: Environment name (dev, staging, prod).
        gateway_instance_id: Unique instance identifier (auto-generated if not provided).
    """

    enabled: bool
    experiment_name: str = "/Shared/a2a-gateway-traces"
    uc_schema: str | None = None
    sql_warehouse_id: str | None = None
    gateway_version: str = "0.1.0"
    gateway_environment: str = "dev"
    gateway_instance_id: str | None = None

    @classmethod
    def from_env(cls) -> "TracingConfig":
        """Create TracingConfig from environment variables.

        Environment variables:
            TRACING_ENABLED: Enable tracing (true/false/1/0)
            MLFLOW_EXPERIMENT_NAME: MLflow experiment path
            TRACE_UC_SCHEMA: Unity Catalog schema (catalog.schema)
            TRACE_SQL_WAREHOUSE_ID: SQL warehouse ID
            GATEWAY_VERSION: Gateway version (from app settings)
            GATEWAY_ENVIRONMENT: Environment name
            GATEWAY_INSTANCE_ID: Instance identifier
        """
        enabled_str = os.getenv("TRACING_ENABLED", "").lower()
        enabled = enabled_str in ("true", "1")

        return cls(
            enabled=enabled,
            experiment_name=os.getenv(
                "MLFLOW_EXPERIMENT_NAME", "/Shared/a2a-gateway-traces"
            ),
            uc_schema=os.getenv("TRACE_UC_SCHEMA"),
            sql_warehouse_id=os.getenv("TRACE_SQL_WAREHOUSE_ID"),
            gateway_version=os.getenv("GATEWAY_VERSION", "0.1.0"),
            gateway_environment=os.getenv("GATEWAY_ENVIRONMENT", "dev"),
            gateway_instance_id=os.getenv("GATEWAY_INSTANCE_ID"),
        )


class TracingConfigurationError(Exception):
    """Raised when tracing configuration fails."""

    pass


def configure_tracing_once(config: TracingConfig) -> None:
    """Configure MLflow tracing at app startup.

    This function configures the experiment for tracing:
    1. Gets the MLflow experiment (must be created by DAB deployment)
    2. Sets the experiment as active
    3. Sets trace destination to Unity Catalog schema (if configured)

    The experiment MUST be created by DAB deployment with proper permissions
    granted to the app's service principal. The app will fail to start if
    the experiment is not found.

    Args:
        config: Tracing configuration.

    Raises:
        TracingConfigurationError: If tracing is enabled but the experiment
            is not found (DAB deployment issue).
    """
    if not config.enabled:
        logger.info("Tracing is disabled, skipping configuration")
        return

    try:
        import mlflow

        # Force mlflow to use Databricks tracking server
        # This is required for Databricks Apps to find workspace experiments
        # Without this, mlflow defaults to local file storage
        previous_uri = mlflow.get_tracking_uri()
        mlflow.set_tracking_uri("databricks")
        logger.info(f"Set mlflow tracking URI to 'databricks' (was: {previous_uri})")

        # Log SQL warehouse ID configuration (optional, for production monitoring)
        sql_warehouse_id = os.getenv("MLFLOW_TRACING_SQL_WAREHOUSE_ID")
        if sql_warehouse_id:
            logger.info(f"SQL warehouse configured for trace monitoring: {sql_warehouse_id[:8]}...")

        # Get the experiment - it MUST exist (created by DAB)
        logger.info(f"Looking for experiment: {config.experiment_name}")
        experiment = mlflow.get_experiment_by_name(config.experiment_name)
        logger.info(f"Experiment lookup result: {experiment}")
        if experiment is None:
            raise TracingConfigurationError(
                f"MLflow experiment '{config.experiment_name}' not found. "
                f"Ensure DAB deployment created the experiment with proper permissions. "
                f"Run 'databricks bundle deploy' to create the experiment."
            )

        # Set as active experiment for tracing
        mlflow.set_experiment(config.experiment_name)
        logger.info(
            f"MLflow tracing active: experiment={config.experiment_name}, "
            f"id={experiment.experiment_id}"
        )

        # Enable autologging to capture nested calls (HTTP, etc.)
        try:
            mlflow.autolog(log_traces=True)
            logger.info("MLflow autolog enabled for automatic tracing")
        except Exception as autolog_err:
            logger.warning(f"Could not enable MLflow autolog: {autolog_err}")

        # Configure trace storage location in Unity Catalog (if configured)
        if config.uc_schema:
            _configure_trace_storage(experiment.experiment_id, config)
        else:
            logger.info("No UC schema configured - traces stored in MLflow only")

    except ImportError as e:
        raise TracingConfigurationError(
            f"MLflow not installed but tracing is enabled. Install mlflow>=2.19.0: {e}"
        )
    except TracingConfigurationError:
        raise
    except Exception as e:
        raise TracingConfigurationError(f"Failed to configure tracing: {e}")


def _configure_trace_storage(experiment_id: str, config: TracingConfig) -> None:
    """Configure Unity Catalog storage for traces.

    Links the experiment to a UC schema using set_experiment_trace_location,
    then sets the runtime destination using set_destination.

    Args:
        experiment_id: MLflow experiment ID to link.
        config: Tracing configuration with uc_schema.
    """
    try:
        import mlflow
        from mlflow.entities import UCSchemaLocation
        from mlflow.tracing.enablement import set_experiment_trace_location

        # Parse catalog and schema from "catalog.schema" format
        parts = config.uc_schema.split(".")
        if len(parts) != 2:
            logger.warning(f"Invalid UC schema format '{config.uc_schema}', expected 'catalog.schema'")
            return

        catalog_name, schema_name = parts
        uc_location = UCSchemaLocation(
            catalog_name=catalog_name,
            schema_name=schema_name,
        )

        # Step 1: Link experiment to UC schema (creates tables if needed)
        logger.info(f"Linking experiment {experiment_id} to UC schema {config.uc_schema}...")
        try:
            result = set_experiment_trace_location(
                location=uc_location,
                experiment_id=experiment_id,
            )
            logger.info(f"set_experiment_trace_location returned: {result}")
            if hasattr(result, 'full_otel_spans_table_name'):
                logger.info(f"Experiment linked to UC table: {result.full_otel_spans_table_name}")
            elif result:
                logger.info(f"Experiment {experiment_id} linked to UC schema {config.uc_schema}")
            else:
                logger.warning(f"set_experiment_trace_location returned empty result")
        except Exception as link_err:
            error_msg = str(link_err).lower()
            if "already" in error_msg or "linked" in error_msg:
                logger.info(f"Experiment already linked to UC schema: {config.uc_schema}")
            else:
                logger.error(f"Failed to link experiment to UC schema: {link_err}", exc_info=True)
                raise TracingConfigurationError(f"Could not link experiment to UC schema: {link_err}")

        # Step 2: Set runtime trace destination
        mlflow.tracing.set_destination(destination=uc_location)
        logger.info(f"Trace destination set: UC schema={config.uc_schema}")

    except ImportError as e:
        logger.warning(f"MLflow tracing imports not available: {e}")
    except Exception as e:
        error_msg = str(e).lower()
        if "already" in error_msg:
            logger.info(f"Trace storage already configured for UC schema: {config.uc_schema}")
        else:
            logger.warning(f"Could not configure trace storage: {e}", exc_info=True)


class GatewayTracer:
    """Tracer for A2A Gateway requests.

    Provides methods for creating traces with standardized tags
    for gateway requests, agent proxy calls, and health checks.
    """

    def __init__(self, config: TracingConfig):
        """Initialize the tracer.

        Args:
            config: Tracing configuration.
        """
        self.config = config
        self.enabled = config.enabled
        self._instance_id = config.gateway_instance_id or self._generate_instance_id()

    @staticmethod
    def _generate_instance_id() -> str:
        """Generate a unique instance ID."""
        return f"gw-{uuid.uuid4().hex[:8]}"

    def build_gateway_tags(self) -> GatewayTags:
        """Build gateway tags from configuration.

        Returns:
            GatewayTags with version, environment, and instance_id.
        """
        return GatewayTags(
            version=self.config.gateway_version,
            environment=self.config.gateway_environment,
            instance_id=self._instance_id,
        )

    def extract_user_tags(self, headers: dict) -> UserTags:
        """Extract user tags from request headers.

        Looks for user email in OBO (On-Behalf-Of) headers:
        - X-Forwarded-Email (primary)
        - X-User-Email (fallback)

        Args:
            headers: Request headers dict (case-insensitive lookup).

        Returns:
            UserTags with email and authenticated status.
        """
        # Normalize headers to lowercase for case-insensitive lookup
        normalized = {k.lower(): v for k, v in headers.items()}

        email = normalized.get("x-forwarded-email") or normalized.get("x-user-email")

        return UserTags(
            email=email,
            authenticated=email is not None,
        )

    def build_agent_tags(
        self,
        name: str,
        connection_id: str,
        url: str | None,
        method: str,
    ) -> AgentTags:
        """Build agent tags for a proxy request.

        Args:
            name: Agent name.
            connection_id: UC connection ID.
            url: Agent URL (may be None if not yet resolved from agent card).
            method: A2A method (send_message, get_task, etc.).

        Returns:
            AgentTags instance.
        """
        return AgentTags(
            name=name,
            connection_id=connection_id,
            url=url,
            method=method,
        )

    def build_request_tags(self, request_id: str, request_type: str) -> RequestTags:
        """Build request tags.

        Args:
            request_id: Unique request/correlation ID.
            request_type: Request type (agent_proxy, gateway, health).

        Returns:
            RequestTags instance.
        """
        return RequestTags(
            id=request_id,
            type=request_type,
        )

    def generate_request_id(self) -> str:
        """Generate a unique request ID.

        Returns:
            UUID-based request ID string.
        """
        return f"req-{uuid.uuid4().hex}"

    @contextmanager
    def trace_request(
        self,
        request_type: str,
        headers: dict,
        request_id: str | None = None,
        agent_tags: AgentTags | None = None,
        span_name: str | None = None,
    ) -> Generator:
        """Context manager for tracing a request.

        Creates an MLflow trace span with standardized tags for
        the gateway, request, user, and optionally agent.

        Args:
            request_type: Request type (agent_proxy, gateway, health).
            headers: Request headers for user extraction.
            request_id: Optional request ID (generated if not provided).
            agent_tags: Optional agent tags for proxy requests.
            span_name: Optional custom span name.

        Yields:
            MLflow span object, or None if tracing is disabled.

        Example:
            with tracer.trace_request(
                request_type="agent_proxy",
                headers=request.headers,
                agent_tags=agent_tags
            ) as span:
                response = await proxy_to_agent(...)
        """
        logger.info(f"trace_request called: enabled={self.enabled}, request_type={request_type}")
        if not self.enabled:
            logger.info("Tracing disabled, skipping trace")
            yield None
            return

        try:
            import mlflow

            # Generate request ID if not provided
            req_id = request_id or self.generate_request_id()

            # Build all tags
            gateway_tags = self.build_gateway_tags()
            request_tags = self.build_request_tags(req_id, request_type)
            user_tags = self.extract_user_tags(headers)

            # Combine into TraceTags
            trace_tags = TraceTags(
                gateway=gateway_tags,
                request=request_tags,
                user=user_tags,
                agent=agent_tags,
            )

            # Determine trace name
            name = span_name or f"gateway.{request_type}"
            if agent_tags:
                name = f"agent.{agent_tags.method}"

            # Convert tags to flat dict
            tags_dict = trace_tags.to_mlflow_tags()
            logger.info(f"Starting mlflow trace: name={name}")

            # Use mlflow.start_span to create a root span (which creates a trace)
            # span_type="CHAIN" indicates this is an orchestration/gateway operation
            with mlflow.start_span(name=name, span_type="CHAIN") as span:
                logger.info(f"Trace started: request_id={span.request_id if hasattr(span, 'request_id') else 'N/A'}")
                # Set tags on the trace
                try:
                    mlflow.update_current_trace(tags=tags_dict)
                    logger.info(f"Tags set on trace")
                except Exception as tag_err:
                    logger.warning(f"Failed to set trace tags: {tag_err}")
                yield span
            logger.info("Trace completed and should be persisted")

        except ImportError:
            logger.warning("MLflow not installed, trace skipped")
            yield None
        except Exception as e:
            logger.error(f"Tracing error: {e}", exc_info=True)
            yield None


def get_tracer() -> GatewayTracer:
    """Get the singleton GatewayTracer instance.

    Creates the tracer on first call using configuration from environment.

    Returns:
        GatewayTracer instance.
    """
    global _tracer_instance

    if _tracer_instance is None:
        config = TracingConfig.from_env()
        _tracer_instance = GatewayTracer(config)

    return _tracer_instance


def reset_tracer() -> None:
    """Reset the singleton tracer instance.

    Primarily for testing purposes.
    """
    global _tracer_instance
    _tracer_instance = None
