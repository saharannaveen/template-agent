"""Tests for ChatUINotifier Redis pub/sub."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deep_agent.src.claude_code.notifications.chat_ui import ChatUINotifier
from deep_agent.src.claude_code.notifications.models import (
    ChatUIChannelConfig,
    Notification,
)


@pytest.fixture
def chat_ui_config():
    """ChatUI channel config fixture."""
    return ChatUIChannelConfig(
        enabled=True,
        redis_url="redis://localhost:6379/0",
    )


@pytest.fixture
def notification():
    """Sample notification fixture."""
    return Notification(
        type="checkpoint",
        workflow_id="wf-abc123",
        task_name="implement-feature",
        message="Checkpoint: tests passing",
        data={"user_id": "user123", "step": 1},
        cumulative_cost=0.25,
        actions=["continue", "pause"],
    )


@pytest.mark.asyncio
async def test_send_publishes_to_redis(chat_ui_config, notification):
    """Test that send() publishes to the correct Redis channel."""
    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.publish = AsyncMock()

    with patch(
        "deep_agent.src.claude_code.notifications.chat_ui.aioredis.from_url",
        return_value=mock_redis,
    ):
        notifier = ChatUINotifier(chat_ui_config)
        await notifier.send(notification)

        # Verify Redis connection
        mock_redis.ping.assert_called_once()

        # Verify publish
        expected_channel = "loop-engineering:notifications:user123"
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == expected_channel

        # Verify message payload
        published_message = json.loads(call_args[0][1])
        assert published_message["type"] == "checkpoint"
        assert published_message["workflow_id"] == "wf-abc123"
        assert published_message["task_name"] == "implement-feature"
        assert published_message["message"] == "Checkpoint: tests passing"
        assert published_message["cumulative_cost"] == 0.25
        assert published_message["actions"] == ["continue", "pause"]
        assert published_message["data"]["user_id"] == "user123"


@pytest.mark.asyncio
async def test_send_falls_back_to_logging_on_redis_error(
    chat_ui_config, notification, caplog
):
    """Test that send() logs instead of raising when Redis fails."""
    # Mock Redis to fail on publish
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.publish = AsyncMock(side_effect=Exception("Redis connection error"))

    with patch(
        "deep_agent.src.claude_code.notifications.chat_ui.aioredis.from_url",
        return_value=mock_redis,
    ):
        notifier = ChatUINotifier(chat_ui_config)
        # Should not raise
        await notifier.send(notification)

        # Should log error
        assert "Failed to publish to Redis" in caplog.text


@pytest.mark.asyncio
async def test_send_without_redis_library(chat_ui_config, notification, caplog):
    """Test that send() degrades gracefully when redis.asyncio is not installed."""
    with patch(
        "deep_agent.src.claude_code.notifications.chat_ui.REDIS_AVAILABLE", False
    ):
        notifier = ChatUINotifier(chat_ui_config)
        await notifier.send(notification)

        # Should log fallback message
        assert "redis.asyncio not installed" in caplog.text


@pytest.mark.asyncio
async def test_send_uses_anonymous_user_when_no_user_id(chat_ui_config):
    """Test that send() uses 'anonymous' when user_id is not in data."""
    notification = Notification(
        type="checkpoint",
        workflow_id="wf-xyz",
        task_name="task",
        message="message",
        data={},  # No user_id
        cumulative_cost=0.0,
        actions=[],
    )

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.publish = AsyncMock()

    with patch(
        "deep_agent.src.claude_code.notifications.chat_ui.aioredis.from_url",
        return_value=mock_redis,
    ):
        notifier = ChatUINotifier(chat_ui_config)
        await notifier.send(notification)

        # Should use anonymous channel
        expected_channel = "loop-engineering:notifications:anonymous"
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == expected_channel


@pytest.mark.asyncio
async def test_close_releases_redis_connection(chat_ui_config):
    """Test that close() properly closes the Redis connection."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.aclose = AsyncMock()

    with patch(
        "deep_agent.src.claude_code.notifications.chat_ui.aioredis.from_url",
        return_value=mock_redis,
    ):
        notifier = ChatUINotifier(chat_ui_config)
        # Trigger connection
        await notifier._ensure_redis()

        # Close
        await notifier.close()
        mock_redis.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_lazy_connection(chat_ui_config):
    """Test that Redis connection is lazy (only on first send)."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()

    with patch(
        "deep_agent.src.claude_code.notifications.chat_ui.aioredis.from_url",
        return_value=mock_redis,
    ) as mock_from_url:
        notifier = ChatUINotifier(chat_ui_config)

        # No connection yet
        mock_from_url.assert_not_called()

        # First send triggers connection
        notification = Notification(
            type="checkpoint",
            workflow_id="wf",
            task_name="t",
            message="m",
            data={"user_id": "u"},
        )
        await notifier.send(notification)
        mock_from_url.assert_called_once()

        # Second send reuses connection
        await notifier.send(notification)
        mock_from_url.assert_called_once()  # Still only called once
