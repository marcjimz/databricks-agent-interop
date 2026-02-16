"""
Traced Foundry Agent Client

Calls Azure AI Foundry agents with OpenTelemetry tracing enabled.
Traces are sent to Application Insights for observability.

Usage:
    from foundry.traced_agent_client import TracedFoundryClient

    client = TracedFoundryClient()
    response = client.chat("What is 2+2?")
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env():
    """Load environment variables from .env file."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


# Load environment
load_env()


def setup_tracing():
    """Configure OpenTelemetry tracing with Application Insights."""
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        print("Warning: APPLICATIONINSIGHTS_CONNECTION_STRING not set. Tracing disabled.")
        return None

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry import trace

        configure_azure_monitor(
            connection_string=connection_string,
            enable_live_metrics=True,
        )

        tracer = trace.get_tracer(__name__)
        print("Tracing enabled with Application Insights")
        return tracer
    except ImportError as e:
        print(f"Warning: Tracing packages not installed: {e}")
        print("Install with: pip install azure-monitor-opentelemetry opentelemetry-sdk")
        return None


class TracedFoundryClient:
    """Client for calling Azure AI Foundry agents with tracing."""

    def __init__(self, tracer=None):
        self.endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
        self.agent_id = os.environ.get("FOUNDRY_AGENT_ID")
        self.api_version = "2025-05-01"
        self.tracer = tracer or setup_tracing()

        if not self.endpoint:
            raise ValueError("AZURE_AI_PROJECT_ENDPOINT not set")
        if not self.agent_id:
            raise ValueError("FOUNDRY_AGENT_ID not set")

    def _get_token(self) -> str:
        """Get Azure AD token for AI Foundry."""
        import subprocess
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", "https://ai.azure.com", "--query", "accessToken", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()

    def _api_call(self, method: str, path: str, body: Optional[dict] = None, span_name: str = "api_call") -> dict:
        """Make REST API call to Foundry with tracing."""
        url = f"{self.endpoint}{path}?api-version={self.api_version}"
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        data = json.dumps(body).encode() if body else None

        # Wrap in trace span if tracer is available
        if self.tracer:
            with self.tracer.start_as_current_span(span_name) as span:
                span.set_attribute("http.method", method)
                span.set_attribute("http.url", url)
                span.set_attribute("ai.agent_id", self.agent_id)
                if body:
                    span.set_attribute("ai.request_body", json.dumps(body)[:1000])

                try:
                    req = urllib.request.Request(url, data=data, headers=headers, method=method)
                    with urllib.request.urlopen(req) as resp:
                        response_text = resp.read().decode()
                        span.set_attribute("http.status_code", resp.status)
                        span.set_attribute("ai.response_body", response_text[:1000])
                        return json.loads(response_text)
                except urllib.error.HTTPError as e:
                    error_body = e.read().decode() if e.fp else str(e)
                    span.set_attribute("http.status_code", e.code)
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", error_body[:500])
                    raise
        else:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode())

    def chat(self, message: str, session_id: Optional[str] = None) -> dict:
        """
        Send a message to the Foundry agent and get a response.

        Args:
            message: The user message to send
            session_id: Optional session ID for multi-turn conversations

        Returns:
            dict with 'response', 'thread_id', 'run_id', and trace info
        """
        parent_span_name = f"foundry_agent_chat"

        if self.tracer:
            with self.tracer.start_as_current_span(parent_span_name) as parent_span:
                parent_span.set_attribute("ai.agent_id", self.agent_id)
                parent_span.set_attribute("ai.user_message", message[:500])
                parent_span.set_attribute("ai.session_id", session_id or "new")

                result = self._execute_chat(message, session_id)

                parent_span.set_attribute("ai.thread_id", result.get("thread_id", ""))
                parent_span.set_attribute("ai.run_id", result.get("run_id", ""))
                parent_span.set_attribute("ai.status", result.get("status", ""))
                if result.get("response"):
                    parent_span.set_attribute("ai.response", result["response"][:500])

                return result
        else:
            return self._execute_chat(message, session_id)

    def _execute_chat(self, message: str, session_id: Optional[str] = None) -> dict:
        """Execute the chat flow: create thread, add message, run, poll, get response."""
        try:
            # Step 1: Create thread
            thread = self._api_call("POST", "/threads", {}, "create_thread")
            thread_id = thread.get("id")

            # Step 2: Add message
            self._api_call("POST", f"/threads/{thread_id}/messages", {
                "role": "user",
                "content": message
            }, "add_message")

            # Step 3: Create run
            run = self._api_call("POST", f"/threads/{thread_id}/runs", {
                "assistant_id": self.agent_id
            }, "create_run")
            run_id = run.get("id")

            # Step 4: Poll for completion
            status = "in_progress"
            for _ in range(30):
                run_status = self._api_call("GET", f"/threads/{thread_id}/runs/{run_id}", span_name="poll_run_status")
                status = run_status.get("status")
                if status == "completed":
                    break
                elif status in ["failed", "cancelled", "expired"]:
                    return {
                        "status": status,
                        "error": run_status.get("last_error", {}),
                        "thread_id": thread_id,
                        "run_id": run_id
                    }
                time.sleep(1)

            # Step 5: Get messages
            messages = self._api_call("GET", f"/threads/{thread_id}/messages", span_name="get_messages")
            assistant_response = None
            for msg in messages.get("data", []):
                if msg.get("role") == "assistant":
                    content = msg.get("content", [])
                    if content:
                        assistant_response = content[0].get("text", {}).get("value", "")
                        break

            return {
                "status": "success",
                "response": assistant_response,
                "thread_id": thread_id,
                "run_id": run_id
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }


def main():
    """Test the traced client."""
    print("Testing Traced Foundry Agent Client")
    print("=" * 50)

    try:
        client = TracedFoundryClient()
        print(f"Agent ID: {client.agent_id}")
        print(f"Endpoint: {client.endpoint}")
        print()

        # Test chat
        print("Sending test message...")
        result = client.chat("What is 2 + 2? Please give a brief answer.")

        print(f"Status: {result.get('status')}")
        print(f"Thread ID: {result.get('thread_id')}")
        print(f"Run ID: {result.get('run_id')}")
        print(f"Response: {result.get('response')}")

        if result.get("error"):
            print(f"Error: {result.get('error')}")

        print()
        print("Traces have been sent to Application Insights.")
        print("View them in the Azure Portal or run the MLflow notebook.")

    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
