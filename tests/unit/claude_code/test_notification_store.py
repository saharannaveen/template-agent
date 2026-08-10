"""Tests for notification_store module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from deep_agent.src.claude_code.notification_store import NotificationStore


@pytest.fixture
def store() -> NotificationStore:
    """Create a fresh notification store for each test."""
    return NotificationStore()


@pytest.mark.asyncio
async def test_add_notification(store: NotificationStore) -> None:
    """Test adding a notification."""
    notification_id = await store.add(
        user_id="user_1",
        notification_type="checkpoint",
        workflow_id="wf_123",
        task_name="Build API",
        message="Plan ready for review",
        data={"plan": "Step 1, Step 2"},
    )

    assert notification_id is not None
    assert isinstance(notification_id, str)

    # Verify it was added
    notifications = await store.get_all("user_1")
    assert len(notifications) == 1
    notif = notifications[0]
    assert notif["notification_id"] == notification_id
    assert notif["user_id"] == "user_1"
    assert notif["type"] == "checkpoint"
    assert notif["workflow_id"] == "wf_123"
    assert notif["task_name"] == "Build API"
    assert notif["message"] == "Plan ready for review"
    assert notif["data"] == {"plan": "Step 1, Step 2"}
    assert notif["read"] is False
    assert isinstance(notif["created_at"], datetime)


@pytest.mark.asyncio
async def test_get_all_for_user(store: NotificationStore) -> None:
    """Test retrieving all notifications for a user."""
    await store.add("user_1", "checkpoint", "wf_1", "Task 1", "Message 1")
    await store.add("user_1", "completion", "wf_2", "Task 2", "Message 2")
    await store.add("user_2", "struggle", "wf_3", "Task 3", "Message 3")

    user1_notifs = await store.get_all("user_1")
    assert len(user1_notifs) == 2

    user2_notifs = await store.get_all("user_2")
    assert len(user2_notifs) == 1


@pytest.mark.asyncio
async def test_get_all_empty(store: NotificationStore) -> None:
    """Test getting notifications for user with none."""
    notifications = await store.get_all("nonexistent_user")
    assert notifications == []


@pytest.mark.asyncio
async def test_mark_read(store: NotificationStore) -> None:
    """Test marking a notification as read."""
    notification_id = await store.add(
        "user_1", "checkpoint", "wf_1", "Task 1", "Message 1"
    )

    # Should be unread initially
    notifications = await store.get_all("user_1")
    assert notifications[0]["read"] is False

    # Mark as read
    await store.mark_read(notification_id)

    # Should be read now
    notifications = await store.get_all("user_1")
    assert notifications[0]["read"] is True


@pytest.mark.asyncio
async def test_mark_read_nonexistent(store: NotificationStore) -> None:
    """Test marking a nonexistent notification as read."""
    # Should not raise, just silently ignore
    await store.mark_read("nonexistent_id")


@pytest.mark.asyncio
async def test_unread_count(store: NotificationStore) -> None:
    """Test getting unread notification count."""
    id1 = await store.add("user_1", "checkpoint", "wf_1", "Task 1", "Message 1")
    await store.add("user_1", "completion", "wf_2", "Task 2", "Message 2")
    await store.add("user_1", "struggle", "wf_3", "Task 3", "Message 3")
    await store.add("user_2", "checkpoint", "wf_4", "Task 4", "Message 4")

    # User 1 should have 3 unread
    count = await store.unread_count("user_1")
    assert count == 3

    # Mark one as read
    await store.mark_read(id1)

    # User 1 should have 2 unread
    count = await store.unread_count("user_1")
    assert count == 2

    # User 2 should have 1 unread
    count = await store.unread_count("user_2")
    assert count == 1


@pytest.mark.asyncio
async def test_unread_count_empty(store: NotificationStore) -> None:
    """Test unread count for user with no notifications."""
    count = await store.unread_count("nonexistent_user")
    assert count == 0


@pytest.mark.asyncio
async def test_thread_safety(store: NotificationStore) -> None:
    """Test concurrent operations are thread-safe."""
    async def add_notification(idx: int) -> None:
        await store.add(
            "user_1",
            "checkpoint",
            f"wf_{idx}",
            f"Task {idx}",
            f"Message {idx}",
        )

    # Add 10 notifications concurrently
    await asyncio.gather(*[add_notification(i) for i in range(10)])

    notifications = await store.get_all("user_1")
    assert len(notifications) == 10


@pytest.mark.asyncio
async def test_notification_ordering(store: NotificationStore) -> None:
    """Test that notifications are returned newest first."""
    # Add notifications with small delay to ensure different timestamps
    id1 = await store.add("user_1", "checkpoint", "wf_1", "Task 1", "Message 1")
    await asyncio.sleep(0.01)
    id2 = await store.add("user_1", "completion", "wf_2", "Task 2", "Message 2")
    await asyncio.sleep(0.01)
    id3 = await store.add("user_1", "struggle", "wf_3", "Task 3", "Message 3")

    notifications = await store.get_all("user_1")
    assert len(notifications) == 3
    # Should be newest first
    assert notifications[0]["notification_id"] == id3
    assert notifications[1]["notification_id"] == id2
    assert notifications[2]["notification_id"] == id1


@pytest.mark.asyncio
async def test_notification_types(store: NotificationStore) -> None:
    """Test all notification types."""
    types = ["checkpoint", "completion", "struggle", "cost_alert"]
    for notif_type in types:
        await store.add("user_1", notif_type, "wf_1", "Task", f"{notif_type} message")

    notifications = await store.get_all("user_1")
    assert len(notifications) == 4
    stored_types = {n["type"] for n in notifications}
    assert stored_types == set(types)


@pytest.mark.asyncio
async def test_notification_with_optional_data(store: NotificationStore) -> None:
    """Test notification with optional data field."""
    notification_id = await store.add(
        "user_1",
        "checkpoint",
        "wf_1",
        "Task 1",
        "Message 1",
        data={"key1": "value1", "key2": 42},
    )

    notifications = await store.get_all("user_1")
    assert len(notifications) == 1
    assert notifications[0]["data"] == {"key1": "value1", "key2": 42}


@pytest.mark.asyncio
async def test_notification_without_data(store: NotificationStore) -> None:
    """Test notification without optional data field."""
    notification_id = await store.add(
        "user_1",
        "checkpoint",
        "wf_1",
        "Task 1",
        "Message 1",
    )

    notifications = await store.get_all("user_1")
    assert len(notifications) == 1
    assert notifications[0]["data"] == {}


@pytest.mark.asyncio
async def test_created_at_timestamp(store: NotificationStore) -> None:
    """Test that created_at is set to current UTC time."""
    before = datetime.now(timezone.utc)
    await store.add("user_1", "checkpoint", "wf_1", "Task", "Message")
    after = datetime.now(timezone.utc)

    notifications = await store.get_all("user_1")
    created_at = notifications[0]["created_at"]
    assert isinstance(created_at, datetime)
    assert before <= created_at <= after
    assert created_at.tzinfo == timezone.utc
