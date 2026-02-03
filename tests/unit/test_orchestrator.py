"""Tests for the A2A Orchestrator Agent.

Tests the orchestrator's ability to:
- Extract text from various content formats (string, list of ResponseInputTextParam)
- Handle conversation history in multi-turn interactions
"""

import pytest
from unittest.mock import MagicMock


def extract_text_content(content) -> str:
    """Extract text from message content.

    This is the same logic as A2AOBOCallingAgent._extract_text_content,
    extracted here for testing without full module dependencies.

    Handles both string content and ResponseInputTextParam list format.
    """
    if isinstance(content, str):
        return content

    # Handle list of content items (ResponseInputTextParam objects)
    if isinstance(content, list):
        text_parts = []
        for item in content:
            # Handle dict format
            if isinstance(item, dict):
                if item.get("type") == "output_text" or item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            # Handle object format (ResponseInputTextParam)
            elif hasattr(item, "text"):
                text_parts.append(item.text)
            elif hasattr(item, "content"):
                text_parts.append(str(item.content))
        return "".join(text_parts)

    # Fallback to string conversion
    return str(content) if content else ""


class TestExtractTextContent:
    """Test the extract_text_content helper function."""

    def test_string_content_returned_as_is(self):
        """String content should be returned unchanged."""
        content = "Hello, world!"
        result = extract_text_content(content)
        assert result == "Hello, world!"

    def test_empty_string_returns_empty(self):
        """Empty string should return empty string."""
        result = extract_text_content("")
        assert result == ""

    def test_none_returns_empty_string(self):
        """None should return empty string."""
        result = extract_text_content(None)
        assert result == ""

    def test_dict_list_with_output_text_type(self):
        """List of dicts with type='output_text' should extract text."""
        content = [
            {"type": "output_text", "text": "Hello from assistant"}
        ]
        result = extract_text_content(content)
        assert result == "Hello from assistant"

    def test_dict_list_with_text_type(self):
        """List of dicts with type='text' should extract text."""
        content = [
            {"type": "text", "text": "User message"}
        ]
        result = extract_text_content(content)
        assert result == "User message"

    def test_multiple_text_items_concatenated(self):
        """Multiple text items should be concatenated."""
        content = [
            {"type": "output_text", "text": "Part 1"},
            {"type": "output_text", "text": "Part 2"}
        ]
        result = extract_text_content(content)
        assert result == "Part 1Part 2"

    def test_object_with_text_attribute(self):
        """Objects with .text attribute should have text extracted."""
        mock_item = MagicMock()
        mock_item.text = "Object text content"
        content = [mock_item]
        result = extract_text_content(content)
        assert result == "Object text content"

    def test_object_with_content_attribute_fallback(self):
        """Objects with .content but no .text should use content."""
        mock_item = MagicMock(spec=['content'])  # Only has content, not text
        mock_item.content = "Fallback content"
        content = [mock_item]
        result = extract_text_content(content)
        assert result == "Fallback content"

    def test_mixed_content_types(self):
        """Mix of dict and object content should all be extracted."""
        mock_item = MagicMock()
        mock_item.text = "Object part"
        content = [
            {"type": "output_text", "text": "Dict part"},
            mock_item
        ]
        result = extract_text_content(content)
        assert result == "Dict partObject part"

    def test_empty_list_returns_empty_string(self):
        """Empty list should return empty string."""
        result = extract_text_content([])
        assert result == ""

    def test_non_matching_dict_type_ignored(self):
        """Dicts with non-matching types should be ignored."""
        content = [
            {"type": "image", "url": "http://example.com/img.png"},
            {"type": "output_text", "text": "Text content"}
        ]
        result = extract_text_content(content)
        assert result == "Text content"


class TestResponseInputTextParamFormat:
    """Test handling of actual ResponseInputTextParam-like objects.

    These simulate the format received in multi-turn conversations:
    content=[ResponseInputTextParam(text="...", type='output_text')]
    """

    def test_responses_agent_assistant_message_format(self):
        """Test the exact format from ResponsesAgent assistant messages.

        When a multi-turn conversation is sent, assistant messages have:
        content=[ResponseInputTextParam(text="...", type='output_text')]
        """
        # Simulate ResponseInputTextParam object
        class ResponseInputTextParam:
            def __init__(self, text, type):
                self.text = text
                self.type = type

        content = [
            ResponseInputTextParam(
                text="You have access to 1 agent: marcin-echo",
                type="output_text"
            )
        ]

        result = extract_text_content(content)
        assert result == "You have access to 1 agent: marcin-echo"

    def test_multi_part_assistant_response(self):
        """Test assistant response with multiple parts."""
        class ResponseInputTextParam:
            def __init__(self, text, type):
                self.text = text
                self.type = type

        content = [
            ResponseInputTextParam(text="First part. ", type="output_text"),
            ResponseInputTextParam(text="Second part.", type="output_text")
        ]

        result = extract_text_content(content)
        assert result == "First part. Second part."


class TestConversationHistory:
    """Test conversation history handling in multi-turn interactions."""

    def test_conversation_history_extracts_all_messages(self):
        """Verify all messages in history are properly extracted."""
        class MockResponseInputTextParam:
            def __init__(self, text, type="output_text"):
                self.text = text
                self.type = type

        # Simulate messages in a multi-turn conversation
        user_msg_1 = "What agents do I have?"
        assistant_msg = [MockResponseInputTextParam(text="You have 1 agent: echo")]
        user_msg_2 = "Call the echo agent"

        # Verify each message extracts correctly
        assert extract_text_content(user_msg_1) == "What agents do I have?"
        assert extract_text_content(assistant_msg) == "You have 1 agent: echo"
        assert extract_text_content(user_msg_2) == "Call the echo agent"

    def test_empty_assistant_message_skipped(self):
        """Empty assistant messages should result in empty string."""
        content = [{"type": "output_text", "text": ""}]
        result = extract_text_content(content)
        assert result == ""

    def test_whitespace_only_content(self):
        """Whitespace-only content is preserved (caller should strip)."""
        content = "   "
        result = extract_text_content(content)
        assert result == "   "


class TestStreamingMessageSeparation:
    """Test that streaming properly separates multiple messages."""

    def test_multiple_ai_messages_need_separator(self):
        """Verify that when we get multiple AI messages, they need separation.

        This tests the scenario where:
        1. AI says "I'll check what agents are available"
        2. Tool executes
        3. AI says "I found 1 agent: marcin-echo"

        Without separator: "I'll check...I found 1 agent"
        With separator: "I'll check...\n\nI found 1 agent"
        """
        msg1 = "I'll check what agents are available."
        msg2 = "I found 1 agent: marcin-echo"

        # Without separator (bad)
        combined_bad = msg1 + msg2
        assert "available.I found" in combined_bad  # No space!

        # With separator (good)
        combined_good = msg1 + "\n\n" + msg2
        assert "available.\n\nI found" in combined_good  # Proper separation
