"""
Foundry Agent Client

Client for calling Azure AI Foundry agents from Databricks.
Uses Entra ID OBO authentication for seamless same-tenant access.
"""
import json
import logging
import os
import time
from typing import Optional
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass
class FoundryResponse:
    """Response from a Foundry agent."""
    status: str
    agent_name: str
    thread_id: str
    response: str
    raw: Optional[dict] = None


class FoundryAgentClient:
    """
    Client for calling Azure AI Foundry agents.

    This client handles:
    - Entra ID authentication (OBO token flow)
    - Thread management for conversations
    - Polling for agent completion

    Usage:
        client = FoundryAgentClient(endpoint="https://your-foundry.cognitiveservices.azure.com")
        response = client.call_agent("my-agent", "Hello!")
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        token: Optional[str] = None,
        timeout: int = 60
    ):
        """
        Initialize the Foundry client.

        Args:
            endpoint: Foundry endpoint URL (or AZURE_AI_FOUNDRY_ENDPOINT env var)
            token: Entra ID token (or will attempt to get from Databricks context)
            timeout: Max seconds to wait for agent response
        """
        self.endpoint = endpoint or os.getenv("AZURE_AI_FOUNDRY_ENDPOINT")
        self._token = token
        self.timeout = timeout

        if not self.endpoint:
            raise ValueError(
                "Foundry endpoint required. Set AZURE_AI_FOUNDRY_ENDPOINT "
                "or pass endpoint parameter."
            )

    @property
    def token(self) -> str:
        """Get authentication token."""
        if self._token:
            return self._token

        # Try to get from Databricks context (OBO token)
        try:
            from pyspark.sql import SparkSession
            spark = SparkSession.builder.getOrCreate()
            token = spark.conf.get("spark.databricks.passthrough.oauthToken", None)
            if token:
                return token
        except Exception:
            pass

        # Try dbutils secrets
        try:
            from databricks.sdk.runtime import dbutils
            return dbutils.secrets.get(scope="azure", key="foundry_token")
        except Exception:
            pass

        # Fallback to environment
        token = os.getenv("AZURE_TOKEN")
        if token:
            return token

        raise ValueError(
            "No authentication token available. Ensure credential passthrough "
            "is enabled or set AZURE_TOKEN environment variable."
        )

    def _headers(self) -> dict:
        """Build request headers."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "api-version": "2024-12-01-preview"
        }

    def create_thread(self, agent_name: str) -> str:
        """
        Create a new conversation thread.

        Args:
            agent_name: Name of the agent

        Returns:
            Thread ID
        """
        url = f"{self.endpoint}/agents/{agent_name}/threads"
        response = requests.post(url, headers=self._headers(), json={})
        response.raise_for_status()
        return response.json().get("id")

    def add_message(
        self,
        agent_name: str,
        thread_id: str,
        message: str,
        role: str = "user"
    ) -> dict:
        """
        Add a message to a thread.

        Args:
            agent_name: Name of the agent
            thread_id: Thread ID
            message: Message content
            role: Message role (user/assistant)

        Returns:
            Message response
        """
        url = f"{self.endpoint}/agents/{agent_name}/threads/{thread_id}/messages"
        response = requests.post(
            url,
            headers=self._headers(),
            json={"role": role, "content": message}
        )
        response.raise_for_status()
        return response.json()

    def run_agent(self, agent_name: str, thread_id: str) -> str:
        """
        Start an agent run on a thread.

        Args:
            agent_name: Name of the agent
            thread_id: Thread ID

        Returns:
            Run ID
        """
        url = f"{self.endpoint}/agents/{agent_name}/threads/{thread_id}/runs"
        response = requests.post(
            url,
            headers=self._headers(),
            json={"assistant_id": agent_name}
        )
        response.raise_for_status()
        return response.json().get("id")

    def wait_for_completion(
        self,
        agent_name: str,
        thread_id: str,
        run_id: str
    ) -> dict:
        """
        Wait for an agent run to complete.

        Args:
            agent_name: Name of the agent
            thread_id: Thread ID
            run_id: Run ID

        Returns:
            Run result

        Raises:
            TimeoutError: If run doesn't complete within timeout
            RuntimeError: If run fails
        """
        url = f"{self.endpoint}/agents/{agent_name}/threads/{thread_id}/runs/{run_id}"
        start_time = time.time()

        while time.time() - start_time < self.timeout:
            response = requests.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            status = data.get("status")

            if status == "completed":
                return data
            elif status in ["failed", "cancelled", "expired"]:
                raise RuntimeError(f"Agent run {status}: {data}")

            time.sleep(1)

        raise TimeoutError(f"Agent run timed out after {self.timeout}s")

    def get_messages(
        self,
        agent_name: str,
        thread_id: str,
        limit: int = 10
    ) -> list:
        """
        Get messages from a thread.

        Args:
            agent_name: Name of the agent
            thread_id: Thread ID
            limit: Max messages to return

        Returns:
            List of messages
        """
        url = f"{self.endpoint}/agents/{agent_name}/threads/{thread_id}/messages"
        response = requests.get(
            url,
            headers=self._headers(),
            params={"order": "desc", "limit": limit}
        )
        response.raise_for_status()
        return response.json().get("data", [])

    def call_agent(
        self,
        agent_name: str,
        message: str,
        thread_id: Optional[str] = None
    ) -> FoundryResponse:
        """
        Call a Foundry agent with a message.

        This is the main entry point for interacting with Foundry agents.
        It handles thread creation, message sending, running, and response extraction.

        Args:
            agent_name: Name of the agent to call
            message: Message to send
            thread_id: Optional existing thread ID for continuity

        Returns:
            FoundryResponse with agent response
        """
        try:
            # Create thread if needed
            if not thread_id:
                thread_id = self.create_thread(agent_name)
                logger.debug(f"Created thread: {thread_id}")

            # Add message
            self.add_message(agent_name, thread_id, message)

            # Run agent
            run_id = self.run_agent(agent_name, thread_id)
            logger.debug(f"Started run: {run_id}")

            # Wait for completion
            self.wait_for_completion(agent_name, thread_id, run_id)

            # Get response
            messages = self.get_messages(agent_name, thread_id, limit=1)
            if messages:
                msg = messages[0]
                content = msg.get("content", [])
                text = next(
                    (c.get("text", {}).get("value", "")
                     for c in content if c.get("type") == "text"),
                    ""
                )
                return FoundryResponse(
                    status="success",
                    agent_name=agent_name,
                    thread_id=thread_id,
                    response=text,
                    raw=msg
                )

            return FoundryResponse(
                status="success",
                agent_name=agent_name,
                thread_id=thread_id,
                response="",
                raw=None
            )

        except Exception as e:
            logger.error(f"Foundry agent call failed: {e}")
            return FoundryResponse(
                status="error",
                agent_name=agent_name,
                thread_id=thread_id or "",
                response=str(e),
                raw=None
            )

    def to_json(self, response: FoundryResponse) -> str:
        """Convert response to JSON string."""
        return json.dumps({
            "status": response.status,
            "agent_name": response.agent_name,
            "thread_id": response.thread_id,
            "response": response.response
        })
