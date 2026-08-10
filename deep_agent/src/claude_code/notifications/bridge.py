"""SSE bridge — subscribes to Redis and converts to SSE format."""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


async def workflow_events(
    user_id: str, redis_url: str = "redis://localhost:6379/0"
) -> AsyncIterator[dict]:
    """Subscribe to workflow notifications for a user and yield SSE events.

    This async generator subscribes to the Redis pub/sub channel for a user
    and converts incoming notifications into SSE-compatible event dictionaries
    that match the format expected by the BFF proxy.

    Args:
        user_id: User ID to subscribe to
        redis_url: Redis connection URL

    Yields:
        Dict with 'type' and 'content' keys in SSE format:
        - type: "workflow_progress"
        - content: notification payload

    Example:
        async for event in workflow_events("user123"):
            # event = {
            #     "type": "workflow_progress",
            #     "content": {
            #         "event": "checkpoint",
            #         "workflow_id": "wf-abc123",
            #         "data": {...}
            #     }
            # }
    """
    if not REDIS_AVAILABLE:
        logger.warning("redis.asyncio not installed, workflow_events disabled")
        return

    channel = f"loop-engineering:notifications:{user_id}"
    redis = None
    pubsub = None

    try:
        redis = aioredis.from_url(redis_url, decode_responses=True)
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        logger.info(f"Subscribed to {channel}")

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                payload = json.loads(message["data"])

                # Convert Redis notification to SSE workflow_progress event
                # Format matches what proxy.router.ts expects for custom events
                sse_event = {
                    "type": "workflow_progress",
                    "event": payload.get("type", "unknown"),
                    "data": {
                        "workflow_id": payload.get("workflow_id"),
                        "task_name": payload.get("task_name"),
                        "message": payload.get("message"),
                        "cumulative_cost": payload.get("cumulative_cost", 0.0),
                        "actions": payload.get("actions", []),
                        **payload.get("data", {}),
                    },
                }

                yield sse_event

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Invalid notification payload: {e}")
                continue

    except Exception as e:
        logger.error(f"workflow_events error: {e}")
        raise
    finally:
        if pubsub is not None:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        if redis is not None:
            await redis.aclose()
