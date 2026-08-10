"""In-memory notification store.

Thread-safe notification store for workflow events. Will be backed by Redis later.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class NotificationStore:
    """Thread-safe in-memory store for notifications.

    Stores notifications for workflow events (checkpoints, completions, struggles, cost alerts).
    Thread-safe using asyncio.Lock.
    """

    def __init__(self) -> None:
        """Initialize the notification store."""
        self._notifications: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def add(
        self,
        user_id: str,
        notification_type: str,
        workflow_id: str,
        task_name: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Add a new notification.

        Args:
            user_id: User to notify
            notification_type: Type (checkpoint/completion/struggle/cost_alert)
            workflow_id: Associated workflow ID
            task_name: Human-readable task name
            message: Notification message
            data: Optional metadata dict

        Returns:
            Generated notification ID
        """
        notification_id = uuid4().hex
        async with self._lock:
            self._notifications[notification_id] = {
                "notification_id": notification_id,
                "user_id": user_id,
                "type": notification_type,
                "workflow_id": workflow_id,
                "task_name": task_name,
                "message": message,
                "data": data or {},
                "read": False,
                "created_at": datetime.now(timezone.utc),
            }
        return notification_id

    async def get_all(self, user_id: str) -> list[dict[str, Any]]:
        """Get all notifications for a user.

        Args:
            user_id: User whose notifications to retrieve

        Returns:
            List of notification dicts (newest first)
        """
        async with self._lock:
            notifications = [
                n for n in self._notifications.values() if n["user_id"] == user_id
            ]
            # Sort by created_at descending (newest first)
            notifications.sort(key=lambda n: n["created_at"], reverse=True)
            return notifications

    async def mark_read(self, notification_id: str) -> None:
        """Mark a notification as read.

        Args:
            notification_id: Notification to mark as read
        """
        async with self._lock:
            if notification_id in self._notifications:
                self._notifications[notification_id]["read"] = True

    async def unread_count(self, user_id: str) -> int:
        """Get count of unread notifications for a user.

        Args:
            user_id: User whose unread count to retrieve

        Returns:
            Number of unread notifications
        """
        async with self._lock:
            return sum(
                1
                for n in self._notifications.values()
                if n["user_id"] == user_id and not n["read"]
            )
