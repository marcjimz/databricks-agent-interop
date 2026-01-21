"""Gateway services for discovery, authorization, and proxying."""

from .discovery import AgentDiscovery, get_discovery
from .authorization import AuthService, get_auth_service
from .proxy import ProxyService, get_proxy_service

__all__ = [
    "AgentDiscovery",
    "get_discovery",
    "AuthService",
    "get_auth_service",
    "ProxyService",
    "get_proxy_service",
]
