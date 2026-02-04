"""Trace tag models for MLflow tracing.

This module defines Pydantic models for trace tags that are logged
to MLflow and synced to Unity Catalog Delta tables.

Experimental Feature: MLflow tracing is in Beta.
"""

from pydantic import BaseModel


class GatewayTags(BaseModel):
    """Gateway-level trace tags.

    These tags identify the gateway instance and are present on all traces.
    """

    version: str
    environment: str
    instance_id: str

    def to_tags_dict(self) -> dict[str, str]:
        """Convert to MLflow tags dict with 'gateway.' prefix."""
        return {
            "gateway.version": self.version,
            "gateway.environment": self.environment,
            "gateway.instance_id": self.instance_id,
        }


class UserTags(BaseModel):
    """User context tags from OBO (On-Behalf-Of) authentication.

    These tags capture the authenticated user making the request.
    """

    email: str | None = None
    authenticated: bool = False

    def to_tags_dict(self) -> dict[str, str]:
        """Convert to MLflow tags dict with 'user.' prefix."""
        tags = {
            "user.authenticated": "true" if self.authenticated else "false",
        }
        if self.email:
            tags["user.email"] = self.email
        return tags


class AgentTags(BaseModel):
    """Agent-specific trace tags.

    These tags are present on traces for agent proxy requests.
    """

    name: str
    connection_id: str
    url: str | None = None
    method: str  # send_message, get_task, cancel_task, message_stream

    def to_tags_dict(self) -> dict[str, str]:
        """Convert to MLflow tags dict with 'agent.' prefix."""
        tags = {
            "agent.name": self.name,
            "agent.connection_id": self.connection_id,
            "agent.method": self.method,
        }
        if self.url:
            tags["agent.url"] = self.url
        return tags


class RequestTags(BaseModel):
    """Request context tags.

    These tags identify the request and its type.
    """

    id: str  # Correlation/request ID
    type: str  # agent_proxy, gateway, health

    def to_tags_dict(self) -> dict[str, str]:
        """Convert to MLflow tags dict with 'request.' prefix."""
        return {
            "request.id": self.id,
            "request.type": self.type,
        }


class TraceTags(BaseModel):
    """Complete trace tags combining all contexts.

    This is the top-level model that combines gateway, request,
    user, and optionally agent tags into a single trace.
    """

    gateway: GatewayTags
    request: RequestTags
    user: UserTags | None = None
    agent: AgentTags | None = None

    def to_mlflow_tags(self) -> dict[str, str]:
        """Flatten all tags to MLflow tag format.

        Returns a flat dictionary with dot-notation keys suitable
        for mlflow.update_current_trace(tags=...).

        None values and missing optional fields are excluded.
        """
        tags = {}

        # Always include gateway and request tags
        tags.update(self.gateway.to_tags_dict())
        tags.update(self.request.to_tags_dict())

        # Include user tags if present
        if self.user:
            tags.update(self.user.to_tags_dict())

        # Include agent tags if present (for agent_proxy requests)
        if self.agent:
            tags.update(self.agent.to_tags_dict())

        return tags
