"""Tests for workflow_routes module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from deep_agent.aegra.workflow_routes import workflow_router
from deep_agent.src.claude_code.workflow_store import WorkflowStore


@pytest.fixture
def test_app():
    """Create a test FastAPI app with the workflow router."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(workflow_router, prefix="/api")
    return app


@pytest.fixture
def client(test_app):
    """Create a test client."""
    return TestClient(test_app)


@pytest.fixture
def mock_workflow_store():
    """Create a mock workflow store."""
    store = MagicMock(spec=WorkflowStore)
    store.get_all = AsyncMock(return_value=[])
    store.get = AsyncMock(return_value=None)
    return store


@pytest.fixture(autouse=True)
def mock_auth():
    """Mock authentication to return a test user ID."""
    with patch(
        "deep_agent.aegra.workflow_routes._authenticated_user_id",
        new_callable=AsyncMock,
        return_value="test_user",
    ) as mock:
        yield mock


def test_get_workflows_empty(client, mock_workflow_store):
    """Test GET /workflows with no workflows."""
    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert data == {"workflows": []}
        mock_workflow_store.get_all.assert_awaited_once_with("test_user")


def test_get_workflows_with_data(client, mock_workflow_store):
    """Test GET /workflows with existing workflows."""
    mock_workflows = [
        {
            "workflow_id": "wf_1",
            "task_name": "Build API",
            "status": "running",
            "current_phase": "implementing",
            "cost": 5.25,
            "iterations": 2,
        },
        {
            "workflow_id": "wf_2",
            "task_name": "Write tests",
            "status": "complete",
            "current_phase": "delivering",
            "cost": 2.50,
            "iterations": 1,
        },
    ]
    mock_workflow_store.get_all = AsyncMock(return_value=mock_workflows)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert data == {"workflows": mock_workflows}


def test_get_workflow_detail_not_found(client, mock_workflow_store):
    """Test GET /workflows/{workflow_id} when workflow doesn't exist."""
    mock_workflow_store.get = AsyncMock(return_value=None)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        response = client.get("/api/workflows/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data


def test_get_workflow_detail_success(client, mock_workflow_store):
    """Test GET /workflows/{workflow_id} success."""
    mock_workflow = {
        "workflow_id": "wf_1",
        "task_name": "Build API",
        "user_id": "test_user",
        "status": "running",
        "current_phase": "implementing",
        "cost": 5.25,
        "iterations": 2,
        "decisions": [
            {"action": "approve", "timestamp": "2024-01-01T00:00:00Z"}
        ],
        "artifacts": [],
    }
    mock_workflow_store.get = AsyncMock(return_value=mock_workflow)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        response = client.get("/api/workflows/wf_1")
        assert response.status_code == 200
        data = response.json()
        assert data == mock_workflow


def test_workflow_action_missing_action_field(client):
    """Test POST /workflows/{workflow_id}/action with missing action field."""
    response = client.post("/api/workflows/wf_1/action", json={})
    assert response.status_code == 422


def test_workflow_action_invalid_action_value(client):
    """Test POST /workflows/{workflow_id}/action with invalid action value."""
    response = client.post(
        "/api/workflows/wf_1/action",
        json={"action": "invalid_action"}
    )
    assert response.status_code == 422


def test_workflow_action_approve(client, mock_workflow_store):
    """Test POST /workflows/{workflow_id}/action with approve action."""
    mock_workflow = {
        "workflow_id": "wf_1",
        "user_id": "test_user",
        "status": "paused",
        "current_phase": "plan_review",
    }
    mock_workflow_store.get = AsyncMock(return_value=mock_workflow)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        with patch("deep_agent.aegra.workflow_routes._send_workflow_signal", new_callable=AsyncMock) as mock_signal:
            response = client.post(
                "/api/workflows/wf_1/action",
                json={"action": "approve"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["action"] == "approve"

            mock_signal.assert_awaited_once()
            call_args = mock_signal.call_args[0]
            assert call_args[0] == "wf_1"
            assert call_args[1]["action"] == "approve"


def test_workflow_action_modify_with_feedback(client, mock_workflow_store):
    """Test POST /workflows/{workflow_id}/action with modify action and feedback."""
    mock_workflow = {
        "workflow_id": "wf_1",
        "user_id": "test_user",
        "status": "paused",
        "current_phase": "plan_review",
    }
    mock_workflow_store.get = AsyncMock(return_value=mock_workflow)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        with patch("deep_agent.aegra.workflow_routes._send_workflow_signal", new_callable=AsyncMock) as mock_signal:
            response = client.post(
                "/api/workflows/wf_1/action",
                json={
                    "action": "modify",
                    "feedback": "Please add error handling"
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["action"] == "modify"

            mock_signal.assert_awaited_once()
            call_args = mock_signal.call_args[0]
            assert call_args[1]["feedback"] == "Please add error handling"


def test_workflow_action_cancel(client, mock_workflow_store):
    """Test POST /workflows/{workflow_id}/action with cancel action."""
    mock_workflow = {
        "workflow_id": "wf_1",
        "user_id": "test_user",
        "status": "running",
        "current_phase": "implementing",
    }
    mock_workflow_store.get = AsyncMock(return_value=mock_workflow)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        with patch("deep_agent.aegra.workflow_routes._send_workflow_signal", new_callable=AsyncMock) as mock_signal:
            response = client.post(
                "/api/workflows/wf_1/action",
                json={"action": "cancel"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["action"] == "cancel"


def test_workflow_action_intervene(client, mock_workflow_store):
    """Test POST /workflows/{workflow_id}/action with intervene action."""
    mock_workflow = {
        "workflow_id": "wf_1",
        "user_id": "test_user",
        "status": "paused",
        "current_phase": "struggle_alert",
    }
    mock_workflow_store.get = AsyncMock(return_value=mock_workflow)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        with patch("deep_agent.aegra.workflow_routes._send_workflow_signal", new_callable=AsyncMock) as mock_signal:
            response = client.post(
                "/api/workflows/wf_1/action",
                json={
                    "action": "intervene",
                    "feedback": "Try using a different approach"
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"


def test_workflow_action_continue(client, mock_workflow_store):
    """Test POST /workflows/{workflow_id}/action with continue action."""
    mock_workflow = {
        "workflow_id": "wf_1",
        "user_id": "test_user",
        "status": "paused",
        "current_phase": "struggle_alert",
    }
    mock_workflow_store.get = AsyncMock(return_value=mock_workflow)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        with patch("deep_agent.aegra.workflow_routes._send_workflow_signal", new_callable=AsyncMock) as mock_signal:
            response = client.post(
                "/api/workflows/wf_1/action",
                json={"action": "continue"}
            )
            assert response.status_code == 200


def test_workflow_action_workflow_not_found(client, mock_workflow_store):
    """Test POST /workflows/{workflow_id}/action when workflow doesn't exist."""
    mock_workflow_store.get = AsyncMock(return_value=None)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        response = client.post(
            "/api/workflows/nonexistent/action",
            json={"action": "approve"}
        )
        assert response.status_code == 404


def test_workflow_action_temporal_unavailable(client, mock_workflow_store):
    """Test action handling when Temporal is unavailable."""
    mock_workflow = {
        "workflow_id": "wf_1",
        "user_id": "test_user",
        "status": "running",
    }
    mock_workflow_store.get = AsyncMock(return_value=mock_workflow)

    with patch("deep_agent.aegra.workflow_routes._get_workflow_store", return_value=mock_workflow_store):
        with patch("deep_agent.aegra.workflow_routes._send_workflow_signal", new_callable=AsyncMock, side_effect=RuntimeError("Temporal not available")):
            response = client.post(
                "/api/workflows/wf_1/action",
                json={"action": "approve"}
            )
            # Should still return 200 but indicate Temporal unavailable
            assert response.status_code == 500
