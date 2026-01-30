"""Gateway services for discovery, authorization, and proxying."""

from .discovery import (
    AgentDiscovery,
    get_discovery,
    extract_token_from_request,
    extract_user_email_from_request,
    AccessDeniedException,
)
from .authorization import AuthService, get_auth_service
from .proxy import ProxyService, get_proxy_service

__all__ = [
    "AgentDiscovery",
    "get_discovery",
    "extract_token_from_request",
    "extract_user_email_from_request",
    "AccessDeniedException",
    "AuthService",
    "get_auth_service",
    "ProxyService",
    "get_proxy_service",
]
