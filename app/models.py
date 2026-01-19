"""Pydantic models for the A2A Gateway."""

from typing import Optional, List
from pydantic import BaseModel


class AgentInfo(BaseModel):
    """Information about a discovered A2A agent."""
    name: str
    description: Optional[str] = None
    url: str
    connection_name: str
    catalog: str
    schema_name: str


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
