"""Tests for notification_routes module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from deep_agent.aegra.notification_routes import notification_router
from deep_agent.src.claude_code.notification_store import NotificationStore


@pytest.fixture
def test_app():
    """Create a test FastAPI app with the notification router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(notification_router, prefix="/api")
    return app


@pytest.fixture
def client(test_app):
    """Create a test client."""
    return TestClient(test_app)


@pytest.fixture
def mock_notification_store():
    """Create a mock notification store."""
    store = MagicMock(spec=NotificationStore)
    store.get_all = AsyncMock(return_value=[])
    store.mark_read = AsyncMock()
    store.unread_count = AsyncMock(return_value=0)
    return store


@pytest.fixture(autouse=True)
def mock_auth():
    """Mock authentication to return a test user ID."""
    with patch(
        "deep_agent.aegra.notification_routes._authenticated_user_id",
        new_callable=AsyncMock,
        return_value="test_user",
    ) as mock:
        yield mock


def test_get_notifications_empty(client, mock_notification_store):
    """Test GET /notifications with no notifications."""
    with patch("deep_agent.aegra.notification_routes._get_notification_store", return_value=mock_notification_store):
        response = client.get("/api/notifications")
        assert response.status_code == 200
        data = response.json()
        assert data == {"notifications": []}
        mock_notification_store.get_all.assert_awaited_once_with("test_user")


def test_get_notifications_with_data(client, mock_notification_store):
    """Test GET /notifications with existing notifications."""
    mock_notifications = [
        {
            "notification_id": "notif_1",
            "type": "checkpoint",
            "workflow_id": "wf_1",
            "task_name": "Build API",
            "message": "Plan ready for review",
            "read": False,
        },
        {
            "notification_id": "notif_2",
            "type": "completion",
            "workflow_id": "wf_2",
            "task_name": "Write tests",
            "message": "Tests complete",
            "read": True,
        },
    ]
    mock_notification_store.get_all = AsyncMock(return_value=mock_notifications)

    with patch("deep_agent.aegra.notification_routes._get_notification_store", return_value=mock_notification_store):
        response = client.get("/api/notifications")
        assert response.status_code == 200
        data = response.json()
        assert data == {"notifications": mock_notifications}


def test_mark_notification_read(client, mock_notification_store):
    """Test POST /notifications/{notification_id}/read."""
    with patch("deep_agent.aegra.notification_routes._get_notification_store", return_value=mock_notification_store):
        response = client.post("/api/notifications/notif_1/read")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": "success"}
        mock_notification_store.mark_read.assert_awaited_once_with("notif_1")


def test_get_unread_count_zero(client, mock_notification_store):
    """Test GET /notifications/unread-count with zero unread."""
    mock_notification_store.unread_count = AsyncMock(return_value=0)

    with patch("deep_agent.aegra.notification_routes._get_notification_store", return_value=mock_notification_store):
        response = client.get("/api/notifications/unread-count")
        assert response.status_code == 200
        data = response.json()
        assert data == {"unread_count": 0}
        mock_notification_store.unread_count.assert_awaited_once_with("test_user")


def test_get_unread_count_with_unread(client, mock_notification_store):
    """Test GET /notifications/unread-count with unread notifications."""
    mock_notification_store.unread_count = AsyncMock(return_value=5)

    with patch("deep_agent.aegra.notification_routes._get_notification_store", return_value=mock_notification_store):
        response = client.get("/api/notifications/unread-count")
        assert response.status_code == 200
        data = response.json()
        assert data == {"unread_count": 5}


def test_notifications_filters_by_user(client, mock_notification_store):
    """Test that notifications are filtered by authenticated user."""
    with patch("deep_agent.aegra.notification_routes._get_notification_store", return_value=mock_notification_store):
        response = client.get("/api/notifications")
        assert response.status_code == 200
        # Verify the store was called with the correct user ID
        mock_notification_store.get_all.assert_awaited_once_with("test_user")


def test_unread_count_filters_by_user(client, mock_notification_store):
    """Test that unread count is filtered by authenticated user."""
    with patch("deep_agent.aegra.notification_routes._get_notification_store", return_value=mock_notification_store):
        response = client.get("/api/notifications/unread-count")
        assert response.status_code == 200
        # Verify the store was called with the correct user ID
        mock_notification_store.unread_count.assert_awaited_once_with("test_user")


def test_mark_read_nonexistent_notification(client, mock_notification_store):
    """Test marking a nonexistent notification as read."""
    # Should succeed silently (store handles nonexistent IDs gracefully)
    with patch("deep_agent.aegra.notification_routes._get_notification_store", return_value=mock_notification_store):
        response = client.post("/api/notifications/nonexistent/read")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": "success"}


def test_notification_types_in_response(client, mock_notification_store):
    """Test that all notification types are properly returned."""
    mock_notifications = [
        {
            "notification_id": "1",
            "type": "checkpoint",
            "workflow_id": "wf_1",
            "task_name": "Task",
            "message": "Checkpoint",
            "read": False,
        },
        {
            "notification_id": "2",
            "type": "completion",
            "workflow_id": "wf_2",
            "task_name": "Task",
            "message": "Complete",
            "read": False,
        },
        {
            "notification_id": "3",
            "type": "struggle",
            "workflow_id": "wf_3",
            "task_name": "Task",
            "message": "Struggling",
            "read": False,
        },
        {
            "notification_id": "4",
            "type": "cost_alert",
            "workflow_id": "wf_4",
            "task_name": "Task",
            "message": "Cost exceeded",
            "read": False,
        },
    ]
    mock_notification_store.get_all = AsyncMock(return_value=mock_notifications)

    with patch("deep_agent.aegra.notification_routes._get_notification_store", return_value=mock_notification_store):
        response = client.get("/api/notifications")
        assert response.status_code == 200
        data = response.json()
        types = {n["type"] for n in data["notifications"]}
        assert types == {"checkpoint", "completion", "struggle", "cost_alert"}
