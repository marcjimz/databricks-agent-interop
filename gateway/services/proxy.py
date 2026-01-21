"""Proxy service for forwarding requests to downstream A2A agents."""

import logging
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import httpx
from fastapi import Request, HTTPException, status

from models import AgentInfo, OAuthM2MCredentials

logger = logging.getLogger(__name__)


class ProxyService:
    """Handles proxying requests to downstream A2A agents."""

    def __init__(self):
        """Initialize the proxy service."""
        self._http_client: Optional[httpx.AsyncClient] = None
        self._agent_card_cache: Dict[str, Dict[str, Any]] = {}
        self._oauth_token_cache: Dict[tuple, tuple] = {}

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client

    async def close(self):
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def fetch_agent_card(self, agent_card_url: str) -> Dict[str, Any]:
        """Fetch and cache an agent card from its URL.

        Args:
            agent_card_url: URL to the agent card JSON.

        Returns:
            The agent card as a dictionary.
        """
        if agent_card_url in self._agent_card_cache:
            return self._agent_card_cache[agent_card_url]

        try:
            response = await self.http_client.get(agent_card_url)
            response.raise_for_status()
            card = response.json()
            self._agent_card_cache[agent_card_url] = card
            logger.info(f"Fetched agent card from {agent_card_url}")
            return card
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch agent card from {agent_card_url}: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch agent card: {str(e)}"
            )

    async def get_agent_endpoint_url(self, agent: AgentInfo) -> str:
        """Get the endpoint URL for an agent by fetching its agent card.

        Args:
            agent: AgentInfo with agent_card_url.

        Returns:
            The endpoint URL from the agent card.
        """
        card = await self.fetch_agent_card(agent.agent_card_url)
        url = card.get("url", "")

        # Handle relative URLs - use agent card URL as base
        if url.startswith("/"):
            parsed = urlparse(agent.agent_card_url)
            url = f"{parsed.scheme}://{parsed.netloc}{url}"

        if not url:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Agent card does not contain a URL"
            )

        return url

    async def acquire_oauth_token(self, oauth_m2m: OAuthM2MCredentials) -> Optional[str]:
        """Acquire an OAuth token using client credentials flow.

        Args:
            oauth_m2m: OAuthM2MCredentials with client_id, client_secret, token_endpoint.

        Returns:
            Access token string or None if acquisition fails.
        """
        cache_key = (oauth_m2m.token_endpoint, oauth_m2m.client_id)

        # Check cache (with 60s buffer before expiry)
        if cache_key in self._oauth_token_cache:
            token, expiry = self._oauth_token_cache[cache_key]
            if time.time() < expiry - 60:
                return token

        try:
            data = {
                "grant_type": "client_credentials",
                "client_id": oauth_m2m.client_id,
                "client_secret": oauth_m2m.client_secret,
            }
            if oauth_m2m.oauth_scope:
                data["scope"] = oauth_m2m.oauth_scope

            response = await self.http_client.post(
                oauth_m2m.token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()
            token_data = response.json()

            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)

            # Cache the token
            self._oauth_token_cache[cache_key] = (access_token, time.time() + expires_in)
            logger.info(f"Acquired OAuth token for {oauth_m2m.client_id}")

            return access_token
        except Exception as e:
            logger.error(f"Failed to acquire OAuth token: {e}")
            return None

    async def build_proxy_headers(
        self,
        agent: AgentInfo,
        request: Request,
        content_type: str = "application/json"
    ) -> Dict[str, str]:
        """Build headers for proxying requests to downstream agents.

        Auth strategy (in priority order):
        1. OAuth M2M: acquire token via client credentials flow
        2. Static bearer_token: use token from UC connection
        3. Databricks pass-through: forward caller's Entra ID token
        """
        headers = {"Content-Type": content_type}

        if agent.oauth_m2m:
            # OAuth M2M: acquire token dynamically
            token = await self.acquire_oauth_token(agent.oauth_m2m)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif agent.bearer_token:
            # Static bearer token from UC connection
            headers["Authorization"] = f"Bearer {agent.bearer_token}"
        elif "authorization" in request.headers:
            # Databricks pass-through: forward caller's Entra ID token
            headers["Authorization"] = request.headers["authorization"]

        return headers

    async def send_message(
        self,
        agent: AgentInfo,
        request: Request,
        body: bytes,
        content_type: str = "application/json"
    ) -> httpx.Response:
        """Send a message to an agent.

        Args:
            agent: The target agent.
            request: The original request (for auth pass-through).
            body: Request body bytes.
            content_type: Content type header.

        Returns:
            The response from the agent.
        """
        agent_url = await self.get_agent_endpoint_url(agent)
        headers = await self.build_proxy_headers(agent, request, content_type)

        try:
            response = await self.http_client.post(
                agent_url,
                content=body,
                headers=headers
            )
            return response
        except httpx.HTTPError as e:
            logger.error(f"Failed to send message to {agent_url}: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to communicate with agent: {str(e)}"
            )

    async def stream_message(
        self,
        agent: AgentInfo,
        request: Request,
        body: bytes
    ):
        """Stream a message to an agent.

        Args:
            agent: The target agent.
            request: The original request (for auth pass-through).
            body: Request body bytes.

        Yields:
            Response chunks from the agent.
        """
        agent_url = await self.get_agent_endpoint_url(agent)
        headers = await self.build_proxy_headers(agent, request)
        headers["Accept"] = "text/event-stream"

        try:
            async with self.http_client.stream(
                "POST",
                agent_url,
                content=body,
                headers=headers
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk
        except httpx.HTTPError as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {{'error': '{str(e)}'}}\n\n".encode()


# Global proxy service instance
_proxy_service: Optional[ProxyService] = None


def get_proxy_service() -> ProxyService:
    """Get the global ProxyService instance."""
    global _proxy_service
    if _proxy_service is None:
        _proxy_service = ProxyService()
    return _proxy_service
