"""Gateway data models."""

from .agent import AgentInfo, OAuthM2MCredentials
from .responses import (
    HealthResponse,
    AgentListResponse,
    ErrorResponse,
    ProxyRequest,
    A2AJsonRpcRequest,
    A2AMessage,
    A2AMessageParams,
    TextPart,
)

__all__ = [
    "AgentInfo",
    "OAuthM2MCredentials",
    "HealthResponse",
    "AgentListResponse",
    "ErrorResponse",
    "ProxyRequest",
    "A2AJsonRpcRequest",
    "A2AMessage",
    "A2AMessageParams",
    "TextPart",
]
