"""Echo Agent - Simple A2A agent that echoes messages back.

This is a minimal A2A agent implementation for demonstration purposes.
"""

import os
from typing import AsyncGenerator, Literal
from pydantic import BaseModel

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, Part, TextPart
from a2a.utils import new_agent_text_message, new_task


class ResponseFormat(BaseModel):
    """Response format for the echo agent."""
    status: Literal["completed", "error"] = "completed"
    message: str


class EchoAgent:
    """Simple echo agent that returns the user's message."""

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]
    SYSTEM_INSTRUCTION = "You are an echo agent. You echo back any message sent to you."

    def __init__(self):
        pass

    async def process(self, query: str, context_id: str) -> AsyncGenerator[dict, None]:
        """Process a message and yield responses.

        Args:
            query: The user's message.
            context_id: The conversation context ID.

        Yields:
            Response dictionaries with content and status.
        """
        # Echo the message back
        echo_response = f"Echo: {query}"

        yield {
            "content": echo_response,
            "is_task_complete": True,
            "require_user_input": False
        }


class EchoAgentExecutor(AgentExecutor):
    """A2A executor for the Echo Agent."""

    def __init__(self):
        self.agent = EchoAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue
    ) -> None:
        """Execute the echo agent for an A2A request.

        Args:
            context: The request context containing the user's message.
            event_queue: Queue for sending events back to the client.
        """
        query = context.get_user_input()
        task = context.current_task or new_task(context.message)

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        async for item in self.agent.process(query, task.context_id):
            if item["is_task_complete"]:
                await updater.add_artifact(
                    [Part(root=TextPart(text=item["content"]))],
                    name="echo_result"
                )
                await updater.complete()
                break
            else:
                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(
                        item["content"], task.context_id, task.id
                    ),
                )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel the current execution."""
        pass


def build_echo_agent_app():
    """Build the Echo Agent A2A application."""
    import httpx
    from a2a.server.apps import A2AStarletteApplication
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import (
        InMemoryTaskStore,
        InMemoryPushNotificationConfigStore,
        BasePushNotificationSender,
    )
    from a2a.types import AgentCapabilities, AgentCard, AgentSkill

    capabilities = AgentCapabilities(
        streaming=True,
        push_notifications=False
    )

    skill = AgentSkill(
        id="echo",
        name="Echo Message",
        description="Echoes back any message sent to it",
        tags=["echo", "test", "demo"],
        examples=["Hello world", "Test message"],
    )

    agent_card = AgentCard(
        name="Echo Agent",
        description="A simple agent that echoes back messages for testing A2A connectivity",
        url="/",
        version="1.0.0",
        default_input_modes=EchoAgent.SUPPORTED_CONTENT_TYPES,
        default_output_modes=EchoAgent.SUPPORTED_CONTENT_TYPES,
        capabilities=capabilities,
        skills=[skill],
    )

    httpx_client = httpx.AsyncClient()
    push_store = InMemoryPushNotificationConfigStore()
    push_sender = BasePushNotificationSender(
        httpx_client=httpx_client,
        config_store=push_store
    )

    request_handler = DefaultRequestHandler(
        agent_executor=EchoAgentExecutor(),
        task_store=InMemoryTaskStore(),
        push_config_store=push_store,
        push_sender=push_sender,
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler
    )
    app = server.build()

    # Add root GET endpoint for browser access
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def get_base_url(request) -> str:
        """Extract the base URL from the request for dynamic agent card URL."""
        # Use X-Forwarded headers if behind a proxy, otherwise use request URL
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        return f"{proto}://{host}"

    async def root(request):
        return JSONResponse({
            "name": agent_card.name,
            "version": agent_card.version,
            "description": agent_card.description,
            "agent_card": "/.well-known/agent.json"
        })

    async def dynamic_agent_card(request):
        """Return agent card with dynamic URL based on request."""
        base_url = get_base_url(request)
        card_data = agent_card.model_dump(mode="json")
        card_data["url"] = base_url  # Set full URL for SDK compatibility
        return JSONResponse(card_data)

    # Insert dynamic agent card endpoints BEFORE the default ones (position 0)
    # This ensures our dynamic version takes precedence
    app.routes.insert(0, Route("/", root, methods=["GET"]))
    app.routes.insert(1, Route("/.well-known/agent.json", dynamic_agent_card, methods=["GET"]))
    app.routes.insert(2, Route("/.well-known/agent-card.json", dynamic_agent_card, methods=["GET"]))

    async def _close_httpx():
        await httpx_client.aclose()
    app.add_event_handler("shutdown", _close_httpx)

    return app


# Create the app for uvicorn
app = build_echo_agent_app()
