"""Calculator Agent with Service Principal authentication.

This agent demonstrates:
1. Using mlflow.genai.agent_server for hosting
2. Service Principal authentication (app's default SP)
3. Simple calculator operations (add, subtract, multiply, divide)
"""

import re
from typing import AsyncGenerator

from databricks.sdk import WorkspaceClient
from mlflow.genai.agent_server import invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
)


def parse_and_calculate(expression: str) -> str:
    """Parse natural language math expression and return result."""
    expression = expression.lower().strip()

    # Extract numbers from expression
    numbers = re.findall(r'-?\d+\.?\d*', expression)
    if len(numbers) < 2:
        return f"Error: Need at least two numbers. Found: {numbers}"

    a, b = float(numbers[0]), float(numbers[1])

    # Determine operation
    if any(op in expression for op in ['add', 'plus', 'sum', '+']):
        result = a + b
        op = '+'
    elif any(op in expression for op in ['subtract', 'minus', 'difference', '-']):
        result = a - b
        op = '-'
    elif any(op in expression for op in ['multiply', 'times', 'product', '*', 'x']):
        result = a * b
        op = '*'
    elif any(op in expression for op in ['divide', 'divided', 'quotient', '/']):
        if b == 0:
            return "Error: Division by zero"
        result = a / b
        op = '/'
    else:
        return f"Error: Unknown operation. Supported: add, subtract, multiply, divide"

    # Format result
    if result == int(result):
        result = int(result)
    return f"{a} {op} {b} = {result}"


def extract_user_message(messages: list) -> str:
    """Extract the last user message from input."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
    return ""


@invoke()
async def invoke(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    """Handle non-streaming invocation."""
    # Use the app's Service Principal for authentication
    ws_client = WorkspaceClient()
    sp_info = ws_client.current_user.me()

    messages = [m.model_dump() for m in request.input]
    expression = extract_user_message(messages)
    result = parse_and_calculate(expression)

    # Include SP info to prove auth worked
    response_text = f"[SP: {sp_info.user_name}] {result}"

    return ResponsesAgentResponse(
        output=[{
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": response_text}]
        }]
    )


@stream()
async def stream(request: ResponsesAgentRequest) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    """Handle streaming invocation."""
    # Use the app's Service Principal for authentication
    ws_client = WorkspaceClient()
    sp_info = ws_client.current_user.me()

    messages = [m.model_dump() for m in request.input]
    expression = extract_user_message(messages)
    result = parse_and_calculate(expression)

    response_text = f"[SP: {sp_info.user_name}] {result}"

    # Stream the response
    yield ResponsesAgentStreamEvent(
        type="response.output_item.done",
        item={
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": response_text}]
        }
    )
