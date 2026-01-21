"""API response models."""

from typing import Optional, List
from pydantic import BaseModel

from .agent import AgentInfo


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
