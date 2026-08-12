"""ChatUINotifier — publishes workflow notifications to Redis pub/sub."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deep_agent.src.claude_code.notifications.models import (
        ChatUIChannelConfig,
        Notification,
    )

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class ChatUINotifier:
    """Publishes notifications to chat UI via Redis pub/sub."""

    def __init__(self, config: ChatUIChannelConfig):
        """Initialize with Redis configuration.

        Args:
            config: ChatUI channel configuration with Redis URL
        """
        self._config = config
        self._redis: aioredis.Redis | None = None

    async def _ensure_redis(self) -> aioredis.Redis | None:
        """Lazily connect to Redis, returning None if unavailable."""
        if not REDIS_AVAILABLE:
            logger.warning("redis.asyncio not installed, ChatUI notifications disabled")
            return None

        if self._redis is None:
            try:
                self._redis = aioredis.from_url(
                    self._config.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                )
                # Test connection
                await self._redis.ping()
                logger.info(f"Connected to Redis at {self._config.redis_url}")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}")
                self._redis = None

        return self._redis

    async def send(self, notification: Notification) -> None:
        """Publish notification to Redis channel.

        Channel: loop-engineering:notifications:{user_id}
        Message format: JSON with type, workflow_id, task_name, message, data

        Falls back to logging if Redis is unavailable.

        Args:
            notification: Notification to send
        """
        redis = await self._ensure_redis()

        if redis is None:
            logger.info(
                f"ChatUI notification (Redis unavailable): {notification.type} "
                f"for {notification.workflow_id} - {notification.message}"
            )
            return

        # Extract user_id from notification data (if available)
        user_id = notification.data.get("user_id", "anonymous")
        channel = f"loop-engineering:notifications:{user_id}"

        # Build message payload
        message = {
            "type": notification.type,
            "workflow_id": notification.workflow_id,
            "task_name": notification.task_name,
            "message": notification.message,
            "data": notification.data,
            "cumulative_cost": notification.cumulative_cost,
            "actions": notification.actions,
        }

        try:
            await redis.publish(channel, json.dumps(message))
            logger.info(
                f"Published {notification.type} to {channel}: {notification.message}"
            )
        except Exception as e:
            logger.error(f"Failed to publish to Redis: {e}")

        # Persist to notification store so GET /api/notifications returns data
        try:
            from deep_agent.src.claude_code.notification_store import NotificationStore

            store = NotificationStore()
            await store.add(
                user_id=user_id,
                notification_type=notification.type,
                workflow_id=notification.workflow_id,
                task_name=notification.task_name,
                message=notification.message,
                data=notification.data,
                url=f"/workflows/{notification.workflow_id}",
            )
        except Exception as e:
            logger.warning(f"Failed to persist notification to store: {e}")

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
