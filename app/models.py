"""Pydantic models for the A2A Gateway."""

from typing import Optional, List
from pydantic import BaseModel


class OAuthM2MCredentials(BaseModel):
    """OAuth Machine-to-Machine credentials for external agents."""
    client_id: str
    client_secret: str
    token_endpoint: str
    oauth_scope: Optional[str] = None


class AgentInfo(BaseModel):
    """Information about a discovered A2A agent."""
    name: str
    description: Optional[str] = None
    agent_card_url: str  # URL to agent card JSON
    url: Optional[str] = None  # Endpoint URL (from agent card)
    # Auth options (mutually exclusive, excluded from API responses)
    bearer_token: Optional[str] = None  # Static token or "databricks" for pass-through
    oauth_m2m: Optional[OAuthM2MCredentials] = None  # OAuth client credentials flow
    connection_name: str
    catalog: str
    schema_name: str

    model_config = {"json_schema_extra": {"properties": {
        "bearer_token": {"writeOnly": True},
        "oauth_m2m": {"writeOnly": True}
    }}}

    def model_dump(self, **kwargs):
        """Exclude auth credentials from serialization by default."""
        kwargs.setdefault("exclude", set())
        if isinstance(kwargs["exclude"], set):
            kwargs["exclude"].add("bearer_token")
            kwargs["exclude"].add("oauth_m2m")
        return super().model_dump(**kwargs)


class AgentListResponse(BaseModel):
    """Response containing list of available agents."""
    agents: List[AgentInfo]
    total: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str


class ProxyRequest(BaseModel):
    """Request to proxy to an A2A agent."""
    agent_name: str
    message: dict


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    detail: Optional[str] = None
