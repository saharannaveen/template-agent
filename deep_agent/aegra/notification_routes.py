"""HTTP routes for workflow notifications."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from deep_agent.src.claude_code.notification_store import NotificationStore
from deep_agent.utils.pylogger import get_python_logger

logger = get_python_logger()

notification_router = APIRouter(tags=["notifications"])

# Global notification store instance (in-memory, Redis-backed later)
_notification_store: NotificationStore | None = None


def _get_notification_store() -> NotificationStore:
    """Get or create the global notification store instance."""
    global _notification_store
    if _notification_store is None:
        _notification_store = NotificationStore()
    return _notification_store


async def _authenticated_user_id(request: Request) -> str:
    """Return the SSO sub from the incoming Bearer token."""
    from deep_agent.aegra.auth import (
        DEV_USER_ID,
        ENABLE_AUTH,
        ENVIRONMENT,
        _decode_token,
    )
    from fastapi import HTTPException

    # Block auth bypass in production
    if ENVIRONMENT == "production" and not ENABLE_AUTH:
        raise HTTPException(
            status_code=500, detail="Authentication bypass disabled in production"
        )

    if not ENABLE_AUTH:
        logger.warning("Auth bypass active for notification routes (development mode)")
        return DEV_USER_ID

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    payload = _decode_token(auth_header[7:])
    return str(payload["sub"])


@notification_router.get("/notifications")
async def get_notifications(request: Request) -> dict[str, Any]:
    """List notifications for current user (newest first)."""
    user_id = await _authenticated_user_id(request)
    store = _get_notification_store()

    notifications = await store.get_all(user_id)

    logger.info(
        "notifications_listed",
        user_id=user_id,
        count=len(notifications),
    )

    return {"notifications": notifications}


@notification_router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str, request: Request
) -> dict[str, str]:
    """Mark a notification as read."""
    user_id = await _authenticated_user_id(request)
    store = _get_notification_store()

    await store.mark_read(notification_id)

    logger.info(
        "notification_marked_read",
        notification_id=notification_id,
        user_id=user_id,
    )

    return {"status": "success"}


@notification_router.get("/notifications/unread-count")
async def get_unread_count(request: Request) -> dict[str, int]:
    """Get unread notification count for current user."""
    user_id = await _authenticated_user_id(request)
    store = _get_notification_store()

    count = await store.unread_count(user_id)

    logger.info(
        "unread_count_retrieved",
        user_id=user_id,
        count=count,
    )

    return {"unread_count": count}
