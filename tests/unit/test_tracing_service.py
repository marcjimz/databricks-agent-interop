"""Unit tests for tracing service."""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock

# Add gateway directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "gateway"))


class TestTracingConfig:
    """Tests for TracingConfig."""

    def test_config_from_env_enabled(self, monkeypatch):
        """TracingConfig loads enabled=true from environment variables."""
        monkeypatch.setenv("TRACING_ENABLED", "true")
        monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "/test/experiment")
        monkeypatch.setenv("TRACE_UC_SCHEMA", "catalog.schema")
        monkeypatch.setenv("GATEWAY_VERSION", "2.0.0")
        monkeypatch.setenv("GATEWAY_ENVIRONMENT", "prod")

        from services.tracing import TracingConfig

        config = TracingConfig.from_env()

        assert config.enabled is True
        assert config.experiment_name == "/test/experiment"
        assert config.uc_schema == "catalog.schema"
        assert config.gateway_version == "2.0.0"
        assert config.gateway_environment == "prod"

    def test_config_defaults(self, monkeypatch):
        """TracingConfig uses defaults when ENV not set."""
        monkeypatch.delenv("TRACING_ENABLED", raising=False)
        monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME", raising=False)
        monkeypatch.delenv("TRACE_UC_SCHEMA", raising=False)
        monkeypatch.delenv("GATEWAY_VERSION", raising=False)
        monkeypatch.delenv("GATEWAY_ENVIRONMENT", raising=False)

        from services.tracing import TracingConfig

        config = TracingConfig.from_env()

        assert config.enabled is False
        assert config.experiment_name == "/Shared/a2a-gateway-traces"
        assert config.uc_schema is None
        assert config.gateway_version == "0.1.0"
        assert config.gateway_environment == "dev"

    def test_config_disabled_when_false(self, monkeypatch):
        """TracingConfig disabled when TRACING_ENABLED=false."""
        monkeypatch.setenv("TRACING_ENABLED", "false")

        from services.tracing import TracingConfig

        config = TracingConfig.from_env()

        assert config.enabled is False

    def test_config_disabled_when_empty(self, monkeypatch):
        """TracingConfig disabled when TRACING_ENABLED is empty."""
        monkeypatch.setenv("TRACING_ENABLED", "")

        from services.tracing import TracingConfig

        config = TracingConfig.from_env()

        assert config.enabled is False

    def test_config_case_insensitive_true(self, monkeypatch):
        """TracingConfig handles TRUE, True, true."""
        for value in ["TRUE", "True", "true", "1"]:
            monkeypatch.setenv("TRACING_ENABLED", value)

            from services.tracing import TracingConfig

            config = TracingConfig.from_env()
            assert config.enabled is True, f"Failed for value: {value}"


class TestConfigureTracingOnce:
    """Tests for tracing setup at app startup."""

    def test_configure_raises_when_experiment_not_found(self):
        """configure_tracing_once raises TracingConfigurationError if experiment doesn't exist."""
        mock_mlflow = MagicMock()
        mock_mlflow.get_experiment_by_name.return_value = None

        with patch.dict(sys.modules, {"mlflow": mock_mlflow}):
            from services.tracing import TracingConfig, TracingConfigurationError, configure_tracing_once

            config = TracingConfig(
                enabled=True,
                experiment_name="/test/experiment",
                uc_schema=None,
                gateway_version="1.0.0",
                gateway_environment="dev",
            )

            with pytest.raises(TracingConfigurationError) as exc_info:
                configure_tracing_once(config)

            assert "/test/experiment" in str(exc_info.value)
            assert "not found" in str(exc_info.value)
            # Should NOT try to create experiment
            mock_mlflow.create_experiment.assert_not_called()

    def test_configure_uses_existing_experiment(self):
        """configure_tracing_once uses existing experiment."""
        mock_mlflow = MagicMock()
        mock_experiment = MagicMock()
        mock_experiment.experiment_id = "exp-456"
        mock_mlflow.get_experiment_by_name.return_value = mock_experiment

        with patch.dict(sys.modules, {"mlflow": mock_mlflow}):
            from services.tracing import TracingConfig, configure_tracing_once

            config = TracingConfig(
                enabled=True,
                experiment_name="/test/experiment",
                uc_schema=None,
                gateway_version="1.0.0",
                gateway_environment="dev",
            )

            configure_tracing_once(config)

            mock_mlflow.create_experiment.assert_not_called()
            mock_mlflow.set_experiment.assert_called_once_with("/test/experiment")

    def test_configure_sets_uc_destination(self):
        """configure_tracing_once sets UC destination when uc_schema provided."""
        mock_mlflow = MagicMock()
        mock_experiment = MagicMock()
        mock_experiment.experiment_id = "exp-789"
        mock_mlflow.get_experiment_by_name.return_value = mock_experiment

        # Mock UCSchemaLocation and set_experiment_trace_location
        mock_uc_schema_location = MagicMock()
        mock_set_trace_location = MagicMock()
        mock_mlflow.entities.UCSchemaLocation = mock_uc_schema_location

        # Create mock modules for mlflow.tracing.enablement
        mock_tracing = MagicMock()
        mock_enablement = MagicMock()
        mock_enablement.set_experiment_trace_location = mock_set_trace_location

        modules = {
            "mlflow": mock_mlflow,
            "mlflow.entities": mock_mlflow.entities,
            "mlflow.tracing": mock_tracing,
            "mlflow.tracing.enablement": mock_enablement,
        }

        with patch.dict(sys.modules, modules):
            from services.tracing import TracingConfig, configure_tracing_once

            config = TracingConfig(
                enabled=True,
                experiment_name="/test/experiment",
                uc_schema="catalog.schema",
                gateway_version="1.0.0",
                gateway_environment="dev",
            )

            configure_tracing_once(config)

            # Should call set_experiment_trace_location and set_destination
            mock_set_trace_location.assert_called_once()
            mock_mlflow.tracing.set_destination.assert_called_once()

    def test_configure_handles_already_set_destination(self):
        """configure_tracing_once handles already set destination gracefully."""
        mock_mlflow = MagicMock()
        mock_experiment = MagicMock()
        mock_experiment.experiment_id = "exp-789"
        mock_mlflow.get_experiment_by_name.return_value = mock_experiment
        mock_mlflow.tracing.set_destination.side_effect = Exception(
            "Destination already set"
        )

        # Mock UCSchemaLocation and set_experiment_trace_location
        mock_uc_schema_location = MagicMock()
        mock_set_trace_location = MagicMock()
        mock_mlflow.entities.UCSchemaLocation = mock_uc_schema_location

        # Create mock modules
        mock_tracing = MagicMock()
        mock_tracing.set_destination = mock_mlflow.tracing.set_destination
        mock_enablement = MagicMock()
        mock_enablement.set_experiment_trace_location = mock_set_trace_location

        modules = {
            "mlflow": mock_mlflow,
            "mlflow.entities": mock_mlflow.entities,
            "mlflow.tracing": mock_tracing,
            "mlflow.tracing.enablement": mock_enablement,
        }

        with patch.dict(sys.modules, modules):
            from services.tracing import TracingConfig, configure_tracing_once

            config = TracingConfig(
                enabled=True,
                experiment_name="/test/experiment",
                uc_schema="catalog.schema",
                gateway_version="1.0.0",
                gateway_environment="dev",
            )

            # Should not raise - handles "already" gracefully
            configure_tracing_once(config)

    def test_configure_skips_when_disabled(self):
        """configure_tracing_once does nothing when disabled."""
        mock_mlflow = MagicMock()

        with patch.dict(sys.modules, {"mlflow": mock_mlflow}):
            from services.tracing import TracingConfig, configure_tracing_once

            config = TracingConfig(
                enabled=False,
                experiment_name="/test/experiment",
                uc_schema=None,
                gateway_version="1.0.0",
                gateway_environment="dev",
            )

            configure_tracing_once(config)

            mock_mlflow.set_experiment.assert_not_called()
            mock_mlflow.create_experiment.assert_not_called()

    def test_configure_skips_uc_destination_when_no_schema(self):
        """configure_tracing_once skips UC destination when uc_schema is None."""
        mock_mlflow = MagicMock()
        mock_experiment = MagicMock()
        mock_experiment.experiment_id = "exp-123"
        mock_mlflow.get_experiment_by_name.return_value = mock_experiment

        with patch.dict(sys.modules, {"mlflow": mock_mlflow}):
            from services.tracing import TracingConfig, configure_tracing_once

            config = TracingConfig(
                enabled=True,
                experiment_name="/test/experiment",
                uc_schema=None,
                gateway_version="1.0.0",
                gateway_environment="dev",
            )

            configure_tracing_once(config)

            mock_mlflow.tracing.set_destination.assert_not_called()

    def test_tracing_configuration_error_exists(self):
        """TracingConfigurationError exception class is available."""
        from services.tracing import TracingConfigurationError

        # Verify the exception class exists and can be raised
        assert TracingConfigurationError is not None

        with pytest.raises(TracingConfigurationError):
            raise TracingConfigurationError("Test error message")


class TestGatewayTracer:
    """Tests for GatewayTracer."""

    def test_tracer_disabled_is_noop(self):
        """GatewayTracer is noop when disabled."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=False,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        assert tracer.enabled is False

    def test_tracer_enabled_flag(self):
        """GatewayTracer reflects enabled state."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        assert tracer.enabled is True

    def test_build_gateway_tags(self):
        """GatewayTracer builds gateway tags from config."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="prod",
            gateway_instance_id="gw-123",
        )
        tracer = GatewayTracer(config)

        tags = tracer.build_gateway_tags()

        assert tags.version == "1.0.0"
        assert tags.environment == "prod"
        assert tags.instance_id == "gw-123"

    def test_build_gateway_tags_generates_instance_id(self):
        """GatewayTracer generates instance_id if not provided."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
            gateway_instance_id=None,
        )
        tracer = GatewayTracer(config)

        tags = tracer.build_gateway_tags()

        assert tags.instance_id is not None
        assert len(tags.instance_id) > 0

    def test_extract_user_tags_from_forwarded_email(self):
        """GatewayTracer extracts email from X-Forwarded-Email."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        headers = {"x-forwarded-email": "user@company.com"}
        user_tags = tracer.extract_user_tags(headers)

        assert user_tags.email == "user@company.com"
        assert user_tags.authenticated is True

    def test_extract_user_tags_from_user_email_header(self):
        """GatewayTracer extracts email from X-User-Email fallback."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        headers = {"x-user-email": "other@company.com"}
        user_tags = tracer.extract_user_tags(headers)

        assert user_tags.email == "other@company.com"
        assert user_tags.authenticated is True

    def test_extract_user_tags_prefers_forwarded_email(self):
        """GatewayTracer prefers X-Forwarded-Email over X-User-Email."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        headers = {
            "x-forwarded-email": "forwarded@company.com",
            "x-user-email": "user@company.com"
        }
        user_tags = tracer.extract_user_tags(headers)

        assert user_tags.email == "forwarded@company.com"

    def test_extract_user_tags_anonymous(self):
        """GatewayTracer returns anonymous when no email header."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        headers = {}
        user_tags = tracer.extract_user_tags(headers)

        assert user_tags.email is None
        assert user_tags.authenticated is False

    def test_extract_user_tags_case_insensitive_headers(self):
        """GatewayTracer handles case-insensitive header names."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        # Headers often come in different cases
        headers = {"X-Forwarded-Email": "user@company.com"}
        user_tags = tracer.extract_user_tags(headers)

        assert user_tags.email == "user@company.com"

    def test_build_agent_tags(self):
        """GatewayTracer builds agent tags."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        agent_tags = tracer.build_agent_tags(
            name="echo-agent",
            connection_id="conn_echo",
            url="https://echo.example.com",
            method="send_message"
        )

        assert agent_tags.name == "echo-agent"
        assert agent_tags.connection_id == "conn_echo"
        assert agent_tags.url == "https://echo.example.com"
        assert agent_tags.method == "send_message"

    def test_build_request_tags(self):
        """GatewayTracer builds request tags."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        request_tags = tracer.build_request_tags(
            request_id="req-123",
            request_type="agent_proxy"
        )

        assert request_tags.id == "req-123"
        assert request_tags.type == "agent_proxy"

    def test_generate_request_id(self):
        """GatewayTracer generates unique request IDs."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        id1 = tracer.generate_request_id()
        id2 = tracer.generate_request_id()

        assert id1 != id2
        assert len(id1) > 0


class TestGetTracer:
    """Tests for tracer singleton."""

    def test_get_tracer_returns_instance(self):
        """get_tracer returns a GatewayTracer instance."""
        from services.tracing import get_tracer, GatewayTracer

        tracer = get_tracer()

        assert isinstance(tracer, GatewayTracer)

    def test_get_tracer_returns_singleton(self, monkeypatch):
        """get_tracer returns same instance on subsequent calls."""
        # Reset singleton for test
        import services.tracing as tracing_module
        monkeypatch.setattr(tracing_module, "_tracer_instance", None)

        from services.tracing import get_tracer

        tracer1 = get_tracer()
        tracer2 = get_tracer()

        assert tracer1 is tracer2


class TestTracerContextManager:
    """Tests for tracer context manager."""

    def test_trace_request_context_manager_enabled(self):
        """GatewayTracer.trace_request works as context manager when enabled."""
        mock_mlflow = MagicMock()
        mock_span = MagicMock()
        mock_mlflow.start_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_mlflow.start_span.return_value.__exit__ = MagicMock(return_value=False)

        with patch.dict(sys.modules, {"mlflow": mock_mlflow}):
            from services.tracing import TracingConfig, GatewayTracer

            config = TracingConfig(
                enabled=True,
                experiment_name="/test",
                uc_schema=None,
                gateway_version="1.0.0",
                gateway_environment="dev",
                gateway_instance_id="gw-123",
            )
            tracer = GatewayTracer(config)

            with tracer.trace_request(
                request_type="gateway",
                headers={}
            ) as span:
                assert span is not None

            mock_mlflow.start_span.assert_called()

    def test_trace_request_disabled_returns_noop(self):
        """GatewayTracer.trace_request returns noop context when disabled."""
        from services.tracing import TracingConfig, GatewayTracer

        config = TracingConfig(
            enabled=False,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
        )
        tracer = GatewayTracer(config)

        with tracer.trace_request(
            request_type="gateway",
            headers={}
        ) as span:
            # Should return None when disabled
            assert span is None

    def test_trace_request_sets_tags(self):
        """GatewayTracer.trace_request sets tags on span."""
        # Import models outside of patch to avoid Pydantic class identity issues
        from services.tracing import TracingConfig, GatewayTracer
        from models.trace import AgentTags

        mock_mlflow = MagicMock()
        mock_span = MagicMock()
        mock_context = MagicMock()
        mock_context.__enter__ = MagicMock(return_value=mock_span)
        mock_context.__exit__ = MagicMock(return_value=False)
        mock_mlflow.start_span.return_value = mock_context

        config = TracingConfig(
            enabled=True,
            experiment_name="/test",
            uc_schema=None,
            gateway_version="1.0.0",
            gateway_environment="dev",
            gateway_instance_id="gw-123",
        )
        tracer = GatewayTracer(config)

        agent_tags = AgentTags(
            name="echo-agent",
            connection_id="conn_echo",
            url="https://echo.example.com",
            method="send_message"
        )

        with patch.dict(sys.modules, {"mlflow": mock_mlflow}):
            with tracer.trace_request(
                request_type="agent_proxy",
                headers={"x-forwarded-email": "user@test.com"},
                agent_tags=agent_tags
            ):
                pass

            # Verify tags were set
            mock_mlflow.update_current_trace.assert_called()
