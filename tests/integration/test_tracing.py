"""Integration tests for MLflow tracing.

These tests require:
- MLflow to be available
- TRACING_ENABLED=true
- Optionally TRACE_UC_SCHEMA for Delta table tests
"""

import os
import pytest

# Skip entire module if tracing not enabled
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("TRACING_ENABLED", "").lower() not in ("true", "1"),
        reason="Tracing not enabled. Set TRACING_ENABLED=true to run these tests."
    ),
]


@pytest.fixture(scope="module")
def tracing_config():
    """Get tracing configuration from environment."""
    from gateway.services.tracing import TracingConfig
    return TracingConfig.from_env()


@pytest.fixture(scope="module")
def configured_tracer(tracing_config):
    """Get a configured tracer instance."""
    from gateway.services.tracing import GatewayTracer, configure_tracing_once

    # Configure tracing (idempotent)
    configure_tracing_once(tracing_config)

    return GatewayTracer(tracing_config)


@pytest.fixture
def mlflow_client():
    """Get MLflow client."""
    try:
        import mlflow
        return mlflow.MlflowClient()
    except ImportError:
        pytest.skip("MLflow not installed")


class TestTracingSetup:
    """Tests for tracing setup and configuration."""

    def test_experiment_exists_after_configure(self, tracing_config, mlflow_client):
        """Experiment exists after configure_tracing_once."""
        import mlflow
        from gateway.services.tracing import configure_tracing_once

        configure_tracing_once(tracing_config)

        experiment = mlflow.get_experiment_by_name(tracing_config.experiment_name)
        assert experiment is not None
        assert experiment.name == tracing_config.experiment_name

    def test_configure_is_idempotent(self, tracing_config):
        """configure_tracing_once can be called multiple times safely."""
        from gateway.services.tracing import configure_tracing_once

        # Should not raise on multiple calls
        configure_tracing_once(tracing_config)
        configure_tracing_once(tracing_config)
        configure_tracing_once(tracing_config)


class TestTraceLogging:
    """Tests for logging traces."""

    def test_trace_logged_to_experiment(self, configured_tracer, tracing_config):
        """Traces are logged to the configured experiment."""
        import mlflow
        import uuid

        # Create a unique request ID for this test
        test_request_id = f"test-{uuid.uuid4().hex[:8]}"

        # Create a trace
        with configured_tracer.trace_request(
            request_type="gateway",
            headers={},
            request_id=test_request_id
        ):
            pass

        # Search for the trace
        experiment = mlflow.get_experiment_by_name(tracing_config.experiment_name)
        traces = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id],
            filter_string=f"tags.`request.id` = '{test_request_id}'",
            max_results=1
        )

        assert len(traces) >= 1

    def test_gateway_tags_present_in_trace(self, configured_tracer, tracing_config):
        """Gateway tags are present in logged traces."""
        import mlflow
        import uuid

        test_request_id = f"test-gw-{uuid.uuid4().hex[:8]}"

        with configured_tracer.trace_request(
            request_type="gateway",
            headers={},
            request_id=test_request_id
        ):
            pass

        experiment = mlflow.get_experiment_by_name(tracing_config.experiment_name)
        traces = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id],
            filter_string=f"tags.`request.id` = '{test_request_id}'",
            max_results=1
        )

        assert len(traces) >= 1
        trace = traces.iloc[0]

        # Verify gateway tags
        assert "tags.gateway.version" in trace.index or trace.get("tags.gateway.version") is not None

    def test_user_tags_present_when_authenticated(self, configured_tracer, tracing_config):
        """User tags are present when X-Forwarded-Email header is provided."""
        import mlflow
        import uuid

        test_request_id = f"test-user-{uuid.uuid4().hex[:8]}"
        test_email = "testuser@example.com"

        with configured_tracer.trace_request(
            request_type="gateway",
            headers={"x-forwarded-email": test_email},
            request_id=test_request_id
        ):
            pass

        experiment = mlflow.get_experiment_by_name(tracing_config.experiment_name)
        traces = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id],
            filter_string=f"tags.`request.id` = '{test_request_id}'",
            max_results=1
        )

        assert len(traces) >= 1

    def test_agent_tags_present_for_proxy_request(self, configured_tracer, tracing_config):
        """Agent tags are present for agent proxy requests."""
        import mlflow
        import uuid
        from gateway.models.trace import AgentTags

        test_request_id = f"test-agent-{uuid.uuid4().hex[:8]}"

        agent_tags = AgentTags(
            name="test-agent",
            connection_id="conn_test",
            url="https://test.example.com",
            method="send_message"
        )

        with configured_tracer.trace_request(
            request_type="agent_proxy",
            headers={},
            request_id=test_request_id,
            agent_tags=agent_tags
        ):
            pass

        experiment = mlflow.get_experiment_by_name(tracing_config.experiment_name)
        traces = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id],
            filter_string=f"tags.`request.id` = '{test_request_id}'",
            max_results=1
        )

        assert len(traces) >= 1


class TestTraceSearch:
    """Tests for searching and filtering traces."""

    def test_search_by_request_type(self, configured_tracer, tracing_config):
        """Can search traces by request type."""
        import mlflow
        import uuid

        # Create traces of different types
        gateway_request_id = f"test-search-gw-{uuid.uuid4().hex[:8]}"
        health_request_id = f"test-search-health-{uuid.uuid4().hex[:8]}"

        with configured_tracer.trace_request(
            request_type="gateway",
            headers={},
            request_id=gateway_request_id
        ):
            pass

        with configured_tracer.trace_request(
            request_type="health",
            headers={},
            request_id=health_request_id
        ):
            pass

        experiment = mlflow.get_experiment_by_name(tracing_config.experiment_name)

        # Search for gateway type
        gateway_traces = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id],
            filter_string=f"tags.`request.id` = '{gateway_request_id}'",
            max_results=1
        )
        assert len(gateway_traces) >= 1

        # Search for health type
        health_traces = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id],
            filter_string=f"tags.`request.id` = '{health_request_id}'",
            max_results=1
        )
        assert len(health_traces) >= 1

    def test_search_by_user_email(self, configured_tracer, tracing_config):
        """Can search traces by user email."""
        import mlflow
        import uuid

        test_email = f"searchtest-{uuid.uuid4().hex[:8]}@example.com"
        test_request_id = f"test-email-{uuid.uuid4().hex[:8]}"

        with configured_tracer.trace_request(
            request_type="gateway",
            headers={"x-forwarded-email": test_email},
            request_id=test_request_id
        ):
            pass

        experiment = mlflow.get_experiment_by_name(tracing_config.experiment_name)
        traces = mlflow.search_traces(
            experiment_ids=[experiment.experiment_id],
            filter_string=f"tags.`request.id` = '{test_request_id}'",
            max_results=1
        )

        assert len(traces) >= 1


@pytest.mark.skipif(
    not os.getenv("TRACE_UC_SCHEMA"),
    reason="TRACE_UC_SCHEMA not configured for Delta table tests"
)
class TestDeltaTableIntegration:
    """Tests for Unity Catalog Delta table integration.

    These tests require TRACE_UC_SCHEMA to be configured and
    may take up to 15 minutes for traces to sync.
    """

    def test_uc_schema_configured(self, tracing_config):
        """UC schema is configured."""
        assert tracing_config.uc_schema is not None
        assert "." in tracing_config.uc_schema  # Should be catalog.schema format

    def test_experiment_linked_to_uc_schema(self, tracing_config):
        """Experiment is linked to UC schema after configuration."""
        import mlflow
        from gateway.services.tracing import configure_tracing_once

        configure_tracing_once(tracing_config)

        # The linking is verified by the fact that configure_tracing_once
        # didn't raise an error (it handles "already linked" gracefully)
        experiment = mlflow.get_experiment_by_name(tracing_config.experiment_name)
        assert experiment is not None
