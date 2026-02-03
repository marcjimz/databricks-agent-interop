"""API response models."""

from typing import Optional, List, Any, Literal
from pydantic import BaseModel, Field

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


# A2A JSON-RPC models for Swagger documentation
class TextPart(BaseModel):
    """A text part in an A2A message."""
    kind: Literal["text"] = "text"
    text: str = Field(..., description="The text content", examples=["Hello, what can you do?"])


class A2AMessage(BaseModel):
    """An A2A protocol message."""
    messageId: str = Field(..., description="Unique message ID", examples=["msg-123"])
    role: Literal["user", "assistant"] = Field("user", description="Message role")
    parts: List[TextPart] = Field(..., description="Message parts (text, file, etc.)")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "messageId": "msg-123",
                "role": "user",
                "parts": [{"kind": "text", "text": "Hello, what can you do?"}]
            }]
        }
    }


class A2AMessageParams(BaseModel):
    """Parameters for message/send method."""
    message: A2AMessage


class A2AJsonRpcRequest(BaseModel):
    """A2A JSON-RPC 2.0 request format.

    Supports all A2A methods: message/send, tasks/get, tasks/cancel, tasks/resubscribe.
    """
    jsonrpc: Literal["2.0"] = Field("2.0", description="JSON-RPC version")
    id: str = Field(..., description="Request ID for correlation", examples=["req-456"])
    method: str = Field(..., description="A2A method (message/send, tasks/get, tasks/cancel, tasks/resubscribe)")
    params: Any = Field(..., description="Method parameters")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "jsonrpc": "2.0",
                "id": "req-456",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "msg-123",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "What is 2 + 2?"}]
                    }
                }
            }]
        }
    }
