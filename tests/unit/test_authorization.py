"""Unit tests for authorization service."""

import pytest
from unittest.mock import Mock, MagicMock, patch

# Add gateway to path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "gateway"))


class TestAuthServiceUserEmail:
    """Tests for user email extraction."""

    def test_get_user_email_from_forwarded_header(self):
        """Test extracting email from x-forwarded-email header."""
        from services.authorization import AuthService

        mock_request = Mock()
        mock_request.headers = {"x-forwarded-email": "user@example.com"}

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = Mock()
            email = service.get_user_email(mock_request)

        assert email == "user@example.com"

    def test_get_user_email_prefers_forwarded_header(self):
        """Test that x-forwarded-email takes precedence over Authorization."""
        from services.authorization import AuthService

        mock_request = Mock()
        mock_request.headers = {
            "x-forwarded-email": "forwarded@example.com",
            "Authorization": "Bearer some-token"
        }

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = Mock()
            email = service.get_user_email(mock_request)

        assert email == "forwarded@example.com"

    def test_get_user_email_no_headers_returns_none(self):
        """Test that missing headers returns None."""
        from services.authorization import AuthService

        mock_request = Mock()
        mock_request.headers = {}

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = Mock()
            email = service.get_user_email(mock_request)

        assert email is None


class TestAuthServiceConnectionAccess:
    """Tests for connection access checking."""

    def test_owner_always_has_access(self):
        """Test that connection owner always has access."""
        from services.authorization import AuthService

        mock_client = Mock()
        mock_connection = Mock()
        mock_connection.owner = "owner@example.com"
        mock_client.connections.get.return_value = mock_connection

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = mock_client

            result = service.check_connection_access("test-conn", "owner@example.com")

        assert result is True

    def test_non_owner_without_grant_denied(self):
        """Test that non-owner without grant is denied."""
        from services.authorization import AuthService

        mock_client = Mock()
        mock_connection = Mock()
        mock_connection.owner = "owner@example.com"
        mock_client.connections.get.return_value = mock_connection
        mock_client.api_client.do.return_value = {"privilege_assignments": []}

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = mock_client

            result = service.check_connection_access("test-conn", "other@example.com")

        assert result is False

    def test_non_owner_with_use_connection_grant_allowed(self):
        """Test that non-owner with USE_CONNECTION grant is allowed."""
        from services.authorization import AuthService

        mock_client = Mock()
        mock_connection = Mock()
        mock_connection.owner = "owner@example.com"
        mock_client.connections.get.return_value = mock_connection
        mock_client.api_client.do.return_value = {
            "privilege_assignments": [
                {
                    "principal": "user@example.com",
                    "privileges": ["USE_CONNECTION"]
                }
            ]
        }

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = mock_client

            result = service.check_connection_access("test-conn", "user@example.com")

        assert result is True

    def test_user_with_other_privileges_denied(self):
        """Test that user with other privileges but not USE_CONNECTION is denied."""
        from services.authorization import AuthService

        mock_client = Mock()
        mock_connection = Mock()
        mock_connection.owner = "owner@example.com"
        mock_client.connections.get.return_value = mock_connection
        mock_client.api_client.do.return_value = {
            "privilege_assignments": [
                {
                    "principal": "user@example.com",
                    "privileges": ["READ_CONNECTION"]
                }
            ]
        }

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = mock_client

            result = service.check_connection_access("test-conn", "user@example.com")

        assert result is False

    def test_connection_not_found_denied(self):
        """Test that non-existent connection is denied."""
        from services.authorization import AuthService

        mock_client = Mock()
        mock_client.connections.get.side_effect = Exception("Connection not found")

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = mock_client

            result = service.check_connection_access("nonexistent-conn", "user@example.com")

        assert result is False


class TestAuthServiceAuthorizeAgentAccess:
    """Tests for authorize_agent_access method."""

    @pytest.mark.asyncio
    async def test_no_user_email_raises_401(self):
        """Test that missing user email raises 401."""
        from services.authorization import AuthService
        from fastapi import HTTPException

        mock_request = Mock()
        mock_request.headers = {}

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = Mock()

            with pytest.raises(HTTPException) as exc_info:
                await service.authorize_agent_access(mock_request, "test-conn")

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_access_raises_403(self):
        """Test that denied access raises 403."""
        from services.authorization import AuthService
        from fastapi import HTTPException

        mock_request = Mock()
        mock_request.headers = {"x-forwarded-email": "user@example.com"}

        mock_client = Mock()
        mock_connection = Mock()
        mock_connection.owner = "owner@example.com"
        mock_client.connections.get.return_value = mock_connection
        mock_client.api_client.do.return_value = {"privilege_assignments": []}

        with patch.object(AuthService, '__init__', lambda x, y=None: None):
            service = AuthService()
            service._client = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await service.authorize_agent_access(mock_request, "test-conn")

            assert exc_info.value.status_code == 403
            assert "USE_CONNECTION" in exc_info.value.detail
