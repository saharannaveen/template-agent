"""Tests for SSE bridge (Redis → SSE event conversion)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deep_agent.src.claude_code.notifications.bridge import workflow_events


class MockAsyncIterator:
    """Mock async iterator for Redis pubsub.listen()."""

    def __init__(self, messages):
        self.messages = messages
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.messages):
            raise StopAsyncIteration
        msg = self.messages[self.index]
        self.index += 1
        return msg


@pytest.mark.asyncio
async def test_workflow_events_converts_checkpoint_notification():
    """Test that workflow_events converts checkpoint notifications to SSE format."""
    # Mock Redis message
    redis_message = {
        "type": "message",
        "data": json.dumps(
            {
                "type": "checkpoint",
                "workflow_id": "wf-abc123",
                "task_name": "implement-feature",
                "message": "Tests passing",
                "cumulative_cost": 0.25,
                "actions": ["continue", "pause"],
                "data": {"step": 1, "user_id": "user123"},
            }
        ),
    }

    # Mock Redis pubsub
    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()
    mock_pubsub.listen = MagicMock(
        return_value=MockAsyncIterator([redis_message])
    )

    mock_redis = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    mock_redis.aclose = AsyncMock()

    with patch(
        "deep_agent.src.claude_code.notifications.bridge.aioredis.from_url",
        return_value=mock_redis,
    ):
        events = []
        async for event in workflow_events("user123"):
            events.append(event)

        assert len(events) == 1
        event = events[0]

        # Verify SSE format
        assert event["type"] == "workflow_progress"
        assert event["event"] == "checkpoint"
        assert event["data"]["workflow_id"] == "wf-abc123"
        assert event["data"]["task_name"] == "implement-feature"
        assert event["data"]["message"] == "Tests passing"
        assert event["data"]["cumulative_cost"] == 0.25
        assert event["data"]["actions"] == ["continue", "pause"]
        assert event["data"]["step"] == 1
        assert event["data"]["user_id"] == "user123"


@pytest.mark.asyncio
async def test_workflow_events_subscribes_to_correct_channel():
    """Test that workflow_events subscribes to the user-specific channel."""
    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()
    mock_pubsub.listen = MagicMock(return_value=MockAsyncIterator([]))

    mock_redis = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    mock_redis.aclose = AsyncMock()

    with patch(
        "deep_agent.src.claude_code.notifications.bridge.aioredis.from_url",
        return_value=mock_redis,
    ):
        async for _ in workflow_events("user456"):
            pass

        # Verify subscription
        expected_channel = "loop-engineering:notifications:user456"
        mock_pubsub.subscribe.assert_called_once_with(expected_channel)


@pytest.mark.asyncio
async def test_workflow_events_skips_non_message_types():
    """Test that workflow_events ignores Redis messages that aren't actual notifications."""
    messages = [
        {"type": "subscribe", "data": None},
        {
            "type": "message",
            "data": json.dumps(
                {
                    "type": "checkpoint",
                    "workflow_id": "wf",
                    "task_name": "t",
                    "message": "m",
                    "data": {},
                }
            ),
        },
        {"type": "unsubscribe", "data": None},
    ]

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()
    mock_pubsub.listen = MagicMock(return_value=MockAsyncIterator(messages))

    mock_redis = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    mock_redis.aclose = AsyncMock()

    with patch(
        "deep_agent.src.claude_code.notifications.bridge.aioredis.from_url",
        return_value=mock_redis,
    ):
        events = []
        async for event in workflow_events("user123"):
            events.append(event)

        # Should only get the actual message
        assert len(events) == 1
        assert events[0]["event"] == "checkpoint"


@pytest.mark.asyncio
async def test_workflow_events_handles_invalid_json():
    """Test that workflow_events skips messages with invalid JSON."""
    messages = [
        {"type": "message", "data": "not-valid-json"},
        {
            "type": "message",
            "data": json.dumps(
                {
                    "type": "completion",
                    "workflow_id": "wf",
                    "task_name": "t",
                    "message": "m",
                    "data": {},
                }
            ),
        },
    ]

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()
    mock_pubsub.listen = MagicMock(return_value=MockAsyncIterator(messages))

    mock_redis = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    mock_redis.aclose = AsyncMock()

    with patch(
        "deep_agent.src.claude_code.notifications.bridge.aioredis.from_url",
        return_value=mock_redis,
    ):
        events = []
        async for event in workflow_events("user123"):
            events.append(event)

        # Should only get the valid message
        assert len(events) == 1
        assert events[0]["event"] == "completion"


@pytest.mark.asyncio
async def test_workflow_events_cleans_up_on_exit():
    """Test that workflow_events unsubscribes and closes connections on exit."""
    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.aclose = AsyncMock()
    mock_pubsub.listen = MagicMock(return_value=MockAsyncIterator([]))

    mock_redis = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    mock_redis.aclose = AsyncMock()

    with patch(
        "deep_agent.src.claude_code.notifications.bridge.aioredis.from_url",
        return_value=mock_redis,
    ):
        async for _ in workflow_events("user123"):
            pass

        # Verify cleanup
        mock_pubsub.unsubscribe.assert_called_once()
        mock_pubsub.aclose.assert_called_once()
        mock_redis.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_workflow_events_without_redis_library():
    """Test that workflow_events degrades gracefully when redis.asyncio is not installed."""
    with patch(
        "deep_agent.src.claude_code.notifications.bridge.REDIS_AVAILABLE", False
    ):
        events = []
        async for event in workflow_events("user123"):
            events.append(event)

        # Should yield nothing
        assert len(events) == 0


@pytest.mark.asyncio
async def test_workflow_events_converts_all_notification_types():
    """Test that workflow_events converts all notification types correctly."""
    notification_types = ["checkpoint", "completion", "struggle", "cost_alert"]

    for notif_type in notification_types:
        redis_message = {
            "type": "message",
            "data": json.dumps(
                {
                    "type": notif_type,
                    "workflow_id": "wf",
                    "task_name": "t",
                    "message": "m",
                    "data": {},
                }
            ),
        }

        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.aclose = AsyncMock()
        mock_pubsub.listen = MagicMock(
            return_value=MockAsyncIterator([redis_message])
        )

        mock_redis = AsyncMock()
        mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
        mock_redis.aclose = AsyncMock()

        with patch(
            "deep_agent.src.claude_code.notifications.bridge.aioredis.from_url",
            return_value=mock_redis,
        ):
            events = []
            async for event in workflow_events("user123"):
                events.append(event)

            assert len(events) == 1
            assert events[0]["event"] == notif_type
