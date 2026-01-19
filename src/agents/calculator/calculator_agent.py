"""Calculator Agent - A2A agent that performs calculations.

This agent uses Databricks LLM for natural language understanding
and tool calling for calculations.
"""

import os
import re
from typing import AsyncGenerator, Literal
from pydantic import BaseModel
from langchain_core.tools import tool

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState, Part, TextPart
from a2a.utils import new_agent_text_message, new_task


@tool
def add(a: float, b: float) -> float:
    """Add two numbers together.

    Args:
        a: First number
        b: Second number

    Returns:
        The sum of a and b
    """
    return a + b


@tool
def subtract(a: float, b: float) -> float:
    """Subtract second number from first.

    Args:
        a: First number
        b: Second number

    Returns:
        a minus b
    """
    return a - b


@tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers.

    Args:
        a: First number
        b: Second number

    Returns:
        The product of a and b
    """
    return a * b


@tool
def divide(a: float, b: float) -> float:
    """Divide first number by second.

    Args:
        a: Dividend
        b: Divisor

    Returns:
        a divided by b

    Raises:
        ValueError: If b is zero
    """
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


class ResponseFormat(BaseModel):
    """Response format for the calculator agent."""
    status: Literal["completed", "input_required", "error"] = "completed"
    message: str
    result: float | None = None


class CalculatorAgent:
    """Calculator agent that performs mathematical operations."""

    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]
    SYSTEM_INSTRUCTION = (
        "You are a calculator assistant. You can perform basic arithmetic: "
        "addition, subtraction, multiplication, and division. "
        "Use the provided tools to calculate results."
    )

    def __init__(self):
        self.tools = [add, subtract, multiply, divide]

        # Try to use Databricks LLM if available
        self.llm = None
        endpoint = os.getenv("DBX_LLM_ENDPOINT")
        if endpoint:
            try:
                from databricks_langchain import ChatDatabricks
                from langgraph.prebuilt import create_react_agent

                self.llm = ChatDatabricks(
                    endpoint=endpoint,
                    temperature=0.0,
                    max_tokens=256,
                )
                self.graph = create_react_agent(
                    self.llm.bind_tools(self.tools),
                    tools=self.tools,
                    prompt=self.SYSTEM_INSTRUCTION,
                )
            except Exception as e:
                print(f"Could not initialize LLM, using rule-based: {e}")
                self.llm = None

    def _parse_simple_expression(self, query: str) -> tuple[str, float, float] | None:
        """Parse a simple arithmetic expression from natural language.

        Args:
            query: User's natural language query.

        Returns:
            Tuple of (operation, a, b) or None if not parseable.
        """
        query = query.lower()

        # Extract numbers
        numbers = re.findall(r'-?\d+\.?\d*', query)
        if len(numbers) < 2:
            return None

        a, b = float(numbers[0]), float(numbers[1])

        # Detect operation
        if any(word in query for word in ['add', 'plus', 'sum', '+']):
            return ('add', a, b)
        elif any(word in query for word in ['subtract', 'minus', 'difference', '-']):
            return ('subtract', a, b)
        elif any(word in query for word in ['multiply', 'times', 'product', '*', 'x']):
            return ('multiply', a, b)
        elif any(word in query for word in ['divide', 'divided', 'quotient', '/']):
            return ('divide', a, b)

        return None

    async def process(self, query: str, context_id: str) -> AsyncGenerator[dict, None]:
        """Process a calculation request.

        Args:
            query: The user's calculation request.
            context_id: The conversation context ID.

        Yields:
            Response dictionaries with calculation results.
        """
        # Try LLM-based processing first
        if self.llm and hasattr(self, 'graph'):
            try:
                async for event in self.graph.astream(
                    {"messages": [{"role": "user", "content": query}]},
                    config={"configurable": {"thread_id": context_id}},
                ):
                    if "agent" in event:
                        messages = event["agent"].get("messages", [])
                        for msg in messages:
                            if hasattr(msg, "content") and msg.content:
                                yield {
                                    "content": msg.content,
                                    "is_task_complete": True,
                                    "require_user_input": False
                                }
                                return
            except Exception as e:
                print(f"LLM processing failed, falling back to rule-based: {e}")

        # Fall back to rule-based processing
        parsed = self._parse_simple_expression(query)

        if parsed is None:
            yield {
                "content": "I couldn't understand that calculation. Please try something like 'add 5 and 3' or 'multiply 4 by 7'.",
                "is_task_complete": False,
                "require_user_input": True
            }
            return

        operation, a, b = parsed

        try:
            if operation == 'add':
                result = add.invoke({"a": a, "b": b})
                response = f"{a} + {b} = {result}"
            elif operation == 'subtract':
                result = subtract.invoke({"a": a, "b": b})
                response = f"{a} - {b} = {result}"
            elif operation == 'multiply':
                result = multiply.invoke({"a": a, "b": b})
                response = f"{a} * {b} = {result}"
            elif operation == 'divide':
                result = divide.invoke({"a": a, "b": b})
                response = f"{a} / {b} = {result}"
            else:
                response = f"Unknown operation: {operation}"

            yield {
                "content": response,
                "is_task_complete": True,
                "require_user_input": False
            }

        except ValueError as e:
            yield {
                "content": f"Error: {str(e)}",
                "is_task_complete": True,
                "require_user_input": False
            }


class CalculatorAgentExecutor(AgentExecutor):
    """A2A executor for the Calculator Agent."""

    def __init__(self):
        self.agent = CalculatorAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue
    ) -> None:
        """Execute the calculator agent for an A2A request."""
        query = context.get_user_input()
        task = context.current_task or new_task(context.message)

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        async for item in self.agent.process(query, task.context_id):
            if item["require_user_input"]:
                await updater.update_status(
                    TaskState.input_required,
                    new_agent_text_message(
                        item["content"], task.context_id, task.id
                    ),
                    final=True,
                )
                break
            elif item["is_task_complete"]:
                await updater.add_artifact(
                    [Part(root=TextPart(text=item["content"]))],
                    name="calculation_result"
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


def build_calculator_agent_app():
    """Build the Calculator Agent A2A application."""
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
        id="calculate",
        name="Basic Arithmetic",
        description="Performs basic arithmetic operations: add, subtract, multiply, divide",
        tags=["calculator", "math", "arithmetic"],
        examples=[
            "Add 5 and 3",
            "What is 10 multiplied by 4?",
            "Divide 100 by 5",
            "Subtract 7 from 15"
        ],
    )

    agent_card = AgentCard(
        name="Calculator Agent",
        description="An A2A agent that performs basic arithmetic calculations",
        url="/",
        version="1.0.0",
        default_input_modes=CalculatorAgent.SUPPORTED_CONTENT_TYPES,
        default_output_modes=CalculatorAgent.SUPPORTED_CONTENT_TYPES,
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
        agent_executor=CalculatorAgentExecutor(),
        task_store=InMemoryTaskStore(),
        push_config_store=push_store,
        push_sender=push_sender,
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler
    )
    app = server.build()

    async def _close_httpx():
        await httpx_client.aclose()
    app.add_event_handler("shutdown", _close_httpx)

    return app


# Create the app for uvicorn
app = build_calculator_agent_app()
