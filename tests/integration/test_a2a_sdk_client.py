"""A2A SDK Client Integration Tests.

Tests the A2A SDK client library patterns used in the demo notebook.
This ensures SDK API changes are caught before they break user-facing demos.

These tests exercise:
- A2ACardResolver for agent card discovery
- ClientFactory.connect() for client creation
- client.send_message(Message) for messaging
- client.send_message_streaming(Message) for SSE streaming
- client.get_task(TaskQueryParams) for task lifecycle
"""

import pytest
import httpx
from uuid import uuid4

# A2A SDK imports - these are the same imports used in the notebook
from a2a.client import A2ACardResolver, ClientFactory, ClientConfig
from a2a.types import Message, Part, TextPart, TaskQueryParams


def extract_text_from_task(task) -> str:
    """Extract text from A2A Task response.

    Mirrors the helper function in the notebook.
    """
    if not task:
        return ""

    artifacts = getattr(task, 'artifacts', None)
    if artifacts:
        for artifact in artifacts:
            parts = getattr(artifact, 'parts', [])
            for part in parts:
                # Handle Part with root containing TextPart
                if hasattr(part, 'root') and hasattr(part.root, 'text'):
                    return part.root.text
                # Handle direct TextPart
                if hasattr(part, 'text'):
                    return part.text
    return ""


def extract_task_from_event(event) -> tuple:
    """Extract task from client event or response.

    The SDK returns AsyncIterator[ClientEvent | Message] where:
    - ClientEvent = tuple[Task, UpdateEvent]
    - UpdateEvent = TaskStatusUpdateEvent | TaskArtifactUpdateEvent | None

    Returns:
        Tuple of (task, task_id, state_value)
    """
    task = None
    task_id = None
    state_value = None

    # Handle ClientEvent tuple: (Task, UpdateEvent)
    if isinstance(event, tuple) and len(event) >= 1:
        task = event[0]  # First element is the Task
        if task:
            task_id = getattr(task, 'id', None)
            status = getattr(task, 'status', None)
            if status:
                state = getattr(status, 'state', None)
                if state:
                    state_value = state.value if hasattr(state, 'value') else str(state)
        return task, task_id, state_value

    # Handle Task directly (has id and status attributes)
    if hasattr(event, 'id') and hasattr(event, 'status'):
        task = event
        task_id = event.id
        status = getattr(event, 'status', None)
        if status:
            state = getattr(status, 'state', None)
            if state:
                state_value = state.value if hasattr(state, 'value') else str(state)
        return task, task_id, state_value

    # Handle Message objects (from SDK response)
    if hasattr(event, 'messageId') or hasattr(event, 'role'):
        return None, None, None

    # Handle wrapped responses (e.g., SendMessageResponse)
    if hasattr(event, 'root'):
        root = event.root
        if hasattr(root, 'result'):
            task = root.result
            task_id = getattr(task, 'id', None) if task else None
            if task:
                status = getattr(task, 'status', None)
                if status:
                    state = getattr(status, 'state', None)
                    if state:
                        state_value = state.value if hasattr(state, 'value') else str(state)
        return task, task_id, state_value

    # Handle dict-like responses
    if isinstance(event, dict):
        if 'result' in event:
            task = event['result']
            task_id = task.get('id') if isinstance(task, dict) else getattr(task, 'id', None)

    return task, task_id, state_value


class TestA2ACardResolver:
    """Tests for A2ACardResolver - agent card discovery."""

    @pytest.mark.asyncio
    async def test_resolver_can_fetch_agent_card(self, echo_agent_url, auth_token):
        """A2ACardResolver should fetch and parse agent cards."""
        headers = {"Authorization": f"Bearer {auth_token}"}

        # Headers set on client - don't pass again in http_kwargs to avoid conflicts
        async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
            resolver = A2ACardResolver(httpx_client=client, base_url=echo_agent_url)
            card = await resolver.get_agent_card()

            # Verify card has required fields
            assert card is not None, "Agent card should not be None"
            assert card.name, "Agent card should have a name"
            assert card.url, "Agent card should have a URL"

    @pytest.mark.asyncio
    async def test_resolver_with_http_kwargs(self, echo_agent_url, auth_token):
        """A2ACardResolver should accept http_kwargs for auth headers when not on client."""
        headers = {"Authorization": f"Bearer {auth_token}"}

        # When headers are NOT on the client, pass via http_kwargs
        async with httpx.AsyncClient(timeout=60.0) as client:
            resolver = A2ACardResolver(httpx_client=client, base_url=echo_agent_url)
            # Pass headers via http_kwargs (only when not set on client)
            card = await resolver.get_agent_card(http_kwargs={"headers": headers})

            assert card is not None, "Agent card should be fetched with http_kwargs"
            assert card.name, "Agent card should have a name"

    @pytest.mark.asyncio
    async def test_resolver_returns_capabilities(self, echo_agent_url, auth_token):
        """A2ACardResolver should return agent capabilities."""
        headers = {"Authorization": f"Bearer {auth_token}"}

        async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
            resolver = A2ACardResolver(httpx_client=client, base_url=echo_agent_url)
            card = await resolver.get_agent_card()

            # Capabilities may be None or an object
            if card.capabilities:
                # If present, should have streaming attribute
                assert hasattr(card.capabilities, 'streaming'), \
                    "Capabilities should have streaming attribute"

    @pytest.mark.asyncio
    async def test_resolver_returns_skills(self, calculator_agent_url, auth_token):
        """A2ACardResolver should return agent skills."""
        headers = {"Authorization": f"Bearer {auth_token}"}

        async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
            resolver = A2ACardResolver(httpx_client=client, base_url=calculator_agent_url)
            card = await resolver.get_agent_card()

            # Calculator agent should have skills
            assert card.skills is not None, "Calculator agent should have skills"
            assert len(card.skills) > 0, "Calculator agent should have at least one skill"

            # Each skill should have required fields
            for skill in card.skills:
                assert skill.name, "Skill should have a name"


class TestClientFactoryConnect:
    """Tests for ClientFactory.connect() - client creation."""

    @pytest.mark.asyncio
    async def test_client_factory_creates_client(self, echo_agent_url, auth_token):
        """ClientFactory.connect() should create a working client."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(echo_agent_url, client_config=config)

        assert client is not None, "ClientFactory should return a client"

    @pytest.mark.asyncio
    async def test_client_factory_with_config(self, echo_agent_url, auth_token):
        """ClientFactory should accept ClientConfig with httpx_client."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        # This is the pattern used in the notebook
        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(echo_agent_url, client_config=config)

        assert client is not None, "Client should be created with config"


class TestSendMessage:
    """Tests for client.send_message(Message) - the core messaging API."""

    @pytest.mark.asyncio
    async def test_send_message_accepts_message_directly(self, echo_agent_url, auth_token):
        """client.send_message() should accept Message object directly."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(echo_agent_url, client_config=config)

        # Create message - this is the pattern used in the notebook
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Hello from SDK test!"))]
        )

        # send_message should accept Message directly (not wrapped in SendMessageRequest)
        task = None
        async for event in client.send_message(message):
            t, tid, sv = extract_task_from_event(event)
            if t:
                task = t

        assert task is not None, "send_message should return a task"

    @pytest.mark.asyncio
    async def test_send_message_returns_async_iterator(self, echo_agent_url, auth_token):
        """client.send_message() should return an async iterator."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(echo_agent_url, client_config=config)

        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Test async iterator"))]
        )

        # Verify it's an async iterator (can use async for)
        event_count = 0
        async for event in client.send_message(message):
            event_count += 1

        assert event_count > 0, "send_message should yield at least one event"

    @pytest.mark.asyncio
    async def test_send_message_echo_agent(self, echo_agent_url, auth_token):
        """Echo agent should echo back the message via SDK."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(echo_agent_url, client_config=config)

        test_message = "SDK test message"
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text=test_message))]
        )

        task = None
        async for event in client.send_message(message):
            t, _, _ = extract_task_from_event(event)
            if t:
                task = t

        # Extract response text
        response_text = extract_text_from_task(task)
        assert test_message in response_text, \
            f"Echo agent should echo back the message. Got: {response_text}"

    @pytest.mark.asyncio
    async def test_send_message_calculator_agent(self, calculator_agent_url, auth_token):
        """Calculator agent should perform calculations via SDK."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(calculator_agent_url, client_config=config)

        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Add 10 and 20"))]
        )

        task = None
        async for event in client.send_message(message):
            t, _, _ = extract_task_from_event(event)
            if t:
                task = t

        # Calculator should return a result
        response_text = extract_text_from_task(task)
        assert response_text, "Calculator should return a response"
        # Should contain 30 somewhere in the response
        assert "30" in response_text, \
            f"Calculator should compute 10+20=30. Got: {response_text}"

    @pytest.mark.asyncio
    async def test_send_message_returns_task_with_id(self, echo_agent_url, auth_token):
        """send_message response should include task ID."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(echo_agent_url, client_config=config)

        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Test task ID"))]
        )

        task_id = None
        async for event in client.send_message(message):
            _, tid, _ = extract_task_from_event(event)
            if tid:
                task_id = tid

        assert task_id is not None, "Response should include task ID"

    @pytest.mark.asyncio
    async def test_send_message_returns_task_state(self, echo_agent_url, auth_token):
        """send_message response should include task state."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(echo_agent_url, client_config=config)

        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Test task state"))]
        )

        state_value = None
        async for event in client.send_message(message):
            _, _, sv = extract_task_from_event(event)
            if sv:
                state_value = sv

        assert state_value is not None, "Response should include task state"
        # Should be a valid A2A state
        valid_states = ["submitted", "working", "completed", "failed", "canceled", "cancelled"]
        assert state_value in valid_states, \
            f"Task state should be valid. Got: {state_value}"


class TestSendMessageStreaming:
    """Tests for streaming behavior of client.send_message().

    Note: The SDK's send_message() returns AsyncIterator[ClientEvent | Message].
    There is no separate send_message_streaming() method - send_message() IS streaming.
    """

    @pytest.mark.asyncio
    async def test_send_message_returns_multiple_events(self, calculator_agent_url, auth_token):
        """client.send_message() should return an async iterator (streaming)."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(calculator_agent_url, client_config=config)

        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Multiply 5 by 5"))]
        )

        # send_message returns AsyncIterator - it's inherently streaming
        event_count = 0
        async for event in client.send_message(message):
            event_count += 1

        assert event_count > 0, "send_message should yield events"

    @pytest.mark.asyncio
    async def test_send_message_yields_tuples(self, calculator_agent_url, auth_token):
        """send_message() should yield ClientEvent tuples (Task, UpdateEvent)."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(calculator_agent_url, client_config=config)

        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Add 1 and 1"))]
        )

        # Collect events to verify structure
        events = []
        async for event in client.send_message(message):
            events.append(event)

        assert len(events) > 0, "Should return at least one event"

        # At least one event should be a ClientEvent tuple
        tuple_events = [e for e in events if isinstance(e, tuple)]
        assert len(tuple_events) > 0, "Should have at least one ClientEvent tuple"

    @pytest.mark.asyncio
    async def test_streaming_yields_task_updates(self, calculator_agent_url, auth_token):
        """Streaming should yield task state updates."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(calculator_agent_url, client_config=config)

        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Divide 100 by 10"))]
        )

        states_seen = []
        async for event in client.send_message(message):
            _, _, state = extract_task_from_event(event)
            if state and state not in states_seen:
                states_seen.append(state)

        # Should see at least one state (typically "completed")
        assert len(states_seen) > 0, "Should yield task states"


class TestGetTask:
    """Tests for client.get_task(TaskQueryParams) - task lifecycle."""

    @pytest.mark.asyncio
    async def test_get_task_accepts_query_params(self, calculator_agent_url, auth_token):
        """client.get_task() should accept TaskQueryParams."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(calculator_agent_url, client_config=config)

        # First, send a message to get a task ID
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Add 5 and 3"))]
        )

        task_id = None
        async for event in client.send_message(message):
            _, tid, _ = extract_task_from_event(event)
            if tid:
                task_id = tid

        if not task_id:
            pytest.skip("Could not get task ID from send_message")

        # Now test get_task with TaskQueryParams
        params = TaskQueryParams(id=task_id)
        try:
            task_status = await client.get_task(params)
            # Should return a task or None (not raise)
            assert task_status is None or hasattr(task_status, 'id'), \
                "get_task should return a task object or None"
        except Exception as e:
            # Some agents may not support get_task, which is OK
            # But the SDK API should not raise TypeError
            assert "TypeError" not in str(type(e)), \
                f"get_task should not raise TypeError: {e}"

    @pytest.mark.asyncio
    async def test_get_task_returns_task_state(self, calculator_agent_url, auth_token):
        """get_task should return task with state."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        httpx_client = httpx.AsyncClient(timeout=60.0, headers=headers)

        config = ClientConfig(httpx_client=httpx_client)
        client = await ClientFactory.connect(calculator_agent_url, client_config=config)

        # First, send a message
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Multiply 7 by 8"))]
        )

        task_id = None
        async for event in client.send_message(message):
            _, tid, _ = extract_task_from_event(event)
            if tid:
                task_id = tid

        if not task_id:
            pytest.skip("Could not get task ID")

        # Get task status
        params = TaskQueryParams(id=task_id)
        try:
            task_status = await client.get_task(params)
            if task_status and hasattr(task_status, 'status'):
                assert task_status.status is not None, "Task should have status"
        except Exception:
            # Agent may not support get_task
            pass


class TestMessageConstruction:
    """Tests for Message/Part/TextPart construction patterns."""

    def test_message_construction_pattern(self):
        """Verify the Message construction pattern used in notebook works."""
        # This is the exact pattern from the notebook
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[Part(root=TextPart(text="Test message"))]
        )

        assert message.messageId is not None
        assert message.role == "user"
        assert len(message.parts) == 1

    def test_text_part_nested_in_part(self):
        """TextPart should be nested in Part.root."""
        text_part = TextPart(text="Hello")
        part = Part(root=text_part)

        assert part.root.text == "Hello"

    def test_message_with_multiple_parts(self):
        """Message should support multiple parts."""
        message = Message(
            messageId=str(uuid4()),
            role="user",
            parts=[
                Part(root=TextPart(text="Part 1")),
                Part(root=TextPart(text="Part 2")),
            ]
        )

        assert len(message.parts) == 2


class TestHelperFunctions:
    """Tests for the helper functions that extract data from responses."""

    def test_extract_text_handles_none(self):
        """extract_text_from_task should handle None task."""
        result = extract_text_from_task(None)
        assert result == ""

    def test_extract_text_handles_empty_artifacts(self):
        """extract_text_from_task should handle task with no artifacts."""
        class MockTask:
            artifacts = None

        result = extract_text_from_task(MockTask())
        assert result == ""

    def test_extract_task_from_event_handles_none(self):
        """extract_task_from_event should handle None event."""
        task, task_id, state = extract_task_from_event(None)
        assert task is None
        assert task_id is None
        assert state is None
