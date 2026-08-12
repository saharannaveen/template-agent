"""Notification store backed by Redis for persistence across restarts.

Falls back to in-memory storage if Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class NotificationStore:
    """Notification store with Redis persistence and in-memory fallback."""

    def __init__(self) -> None:
        """Initialize notification store with in-memory storage and Redis config."""
        self._local: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._redis = None
        self._key_prefix = "loop-eng:notifications:"
        self._user_index_prefix = "loop-eng:notifications:user:"
        self._ttl = 604800  # 7 days

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            return None
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(redis_url, decode_responses=True)
            await self._redis.ping()
            return self._redis
        except Exception:
            self._redis = None
            return None

    def _serialize(self, n: dict) -> str:
        d = dict(n)
        if isinstance(d.get("created_at"), datetime):
            d["created_at"] = d["created_at"].isoformat()
        return json.dumps(d)

    def _deserialize(self, raw: str) -> dict:
        d = json.loads(raw)
        if "created_at" in d and isinstance(d["created_at"], str):
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        return d

    async def add(
        self,
        user_id: str,
        notification_type: str,
        workflow_id: str,
        task_name: str,
        message: str,
        data: dict[str, Any] | None = None,
        url: str | None = None,
    ) -> str:
        """Create and persist a notification, returning its ID."""
        notification_id = uuid4().hex
        notification = {
            "notification_id": notification_id,
            "user_id": user_id,
            "type": notification_type,
            "workflow_id": workflow_id,
            "task_name": task_name,
            "message": message,
            "data": data or {},
            "read": False,
            "url": url or f"/workflows/{workflow_id}",
            "created_at": datetime.now(timezone.utc),
        }

        async with self._lock:
            self._local[notification_id] = notification

        r = await self._get_redis()
        if r:
            try:
                await r.set(
                    f"{self._key_prefix}{notification_id}",
                    self._serialize(notification),
                    ex=self._ttl,
                )
                await r.sadd(f"{self._user_index_prefix}{user_id}", notification_id)
                await r.expire(f"{self._user_index_prefix}{user_id}", self._ttl)
            except Exception as e:
                logger.warning("Failed to persist notification to Redis: %s", e)

        return notification_id

    async def get_all(self, user_id: str) -> list[dict[str, Any]]:
        """Return all notifications for a user, sorted newest first."""
        r = await self._get_redis()
        if r:
            try:
                notification_ids = await r.smembers(
                    f"{self._user_index_prefix}{user_id}"
                )
                if notification_ids:
                    notifications = []
                    for nid in notification_ids:
                        raw = await r.get(f"{self._key_prefix}{nid}")
                        if raw:
                            n = self._deserialize(raw)
                            notifications.append(n)
                            async with self._lock:
                                self._local[nid] = n
                        else:
                            await r.srem(f"{self._user_index_prefix}{user_id}", nid)
                    notifications.sort(
                        key=lambda n: n.get("created_at", datetime.min), reverse=True
                    )
                    return notifications
            except Exception as e:
                logger.warning("Failed to read notifications from Redis: %s", e)

        async with self._lock:
            notifications = [n for n in self._local.values() if n["user_id"] == user_id]
            notifications.sort(
                key=lambda n: n.get("created_at", datetime.min), reverse=True
            )
            return notifications

    async def mark_read(self, notification_id: str) -> None:
        """Mark a notification as read in both local cache and Redis."""
        async with self._lock:
            if notification_id in self._local:
                self._local[notification_id]["read"] = True
                n = self._local[notification_id]
            else:
                n = None

        r = await self._get_redis()
        if r:
            try:
                raw = await r.get(f"{self._key_prefix}{notification_id}")
                if raw:
                    n = self._deserialize(raw)
                    n["read"] = True
                    await r.set(
                        f"{self._key_prefix}{notification_id}",
                        self._serialize(n),
                        ex=self._ttl,
                    )
                    async with self._lock:
                        self._local[notification_id] = n
            except Exception as e:
                logger.warning("Failed to mark notification read in Redis: %s", e)

    async def unread_count(self, user_id: str) -> int:
        """Return the number of unread notifications for a user."""
        notifications = await self.get_all(user_id)
        return sum(1 for n in notifications if not n.get("read", False))
