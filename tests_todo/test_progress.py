"""Tests for the progress tracking feature."""

import pytest
from fastapi.testclient import TestClient

from todo_app.main import app, db
from todo_app.models import TodoCreate, TodoProgress, TodoStatus
from todo_app.database import TodoDatabase


# ---------------------------------------------------------------------------
# Unit tests for TodoProgress model
# ---------------------------------------------------------------------------

class TestTodoProgressModel:
    """Tests for the TodoProgress Pydantic model."""

    def test_progress_all_fields(self):
        p = TodoProgress(
            total=10, not_started=3, in_progress=4, completed=3, percent_complete=30.0
        )
        assert p.total == 10
        assert p.not_started == 3
        assert p.in_progress == 4
        assert p.completed == 3
        assert p.percent_complete == 30.0

    def test_progress_serialization(self):
        p = TodoProgress(
            total=5, not_started=1, in_progress=2, completed=2, percent_complete=40.0
        )
        data = p.model_dump()
        assert data == {
            "total": 5,
            "not_started": 1,
            "in_progress": 2,
            "completed": 2,
            "percent_complete": 40.0,
        }

    def test_progress_zero_total(self):
        p = TodoProgress(
            total=0, not_started=0, in_progress=0, completed=0, percent_complete=0.0
        )
        assert p.percent_complete == 0.0

    def test_progress_hundred_percent(self):
        p = TodoProgress(
            total=3, not_started=0, in_progress=0, completed=3, percent_complete=100.0
        )
        assert p.percent_complete == 100.0


# ---------------------------------------------------------------------------
# Unit tests for TodoDatabase.get_progress
# ---------------------------------------------------------------------------

class TestDatabaseGetProgress:
    """Tests for the get_progress method on TodoDatabase."""

    @pytest.fixture
    def database(self):
        return TodoDatabase()

    def test_progress_empty_database(self, database):
        p = database.get_progress()
        assert p.total == 0
        assert p.not_started == 0
        assert p.in_progress == 0
        assert p.completed == 0
        assert p.percent_complete == 0.0

    def test_progress_all_not_started(self, database):
        database.create(TodoCreate(title="A", description="a"))
        database.create(TodoCreate(title="B", description="b"))
        p = database.get_progress()
        assert p.total == 2
        assert p.not_started == 2
        assert p.in_progress == 0
        assert p.completed == 0
        assert p.percent_complete == 0.0

    def test_progress_all_completed(self, database):
        database.create(
            TodoCreate(title="A", description="a", status="Completed")
        )
        database.create(
            TodoCreate(title="B", description="b", status="Completed")
        )
        p = database.get_progress()
        assert p.total == 2
        assert p.not_started == 0
        assert p.in_progress == 0
        assert p.completed == 2
        assert p.percent_complete == 100.0

    def test_progress_mixed_statuses(self, database):
        database.create(TodoCreate(title="A", description="a"))
        database.create(
            TodoCreate(title="B", description="b", status="In Progress")
        )
        database.create(
            TodoCreate(title="C", description="c", status="Completed")
        )
        p = database.get_progress()
        assert p.total == 3
        assert p.not_started == 1
        assert p.in_progress == 1
        assert p.completed == 1
        assert p.percent_complete == pytest.approx(33.3, abs=0.1)

    def test_progress_after_delete(self, database):
        database.create(TodoCreate(title="A", description="a"))
        item = database.create(
            TodoCreate(title="B", description="b", status="Completed")
        )
        database.delete(item.id)
        p = database.get_progress()
        assert p.total == 1
        assert p.completed == 0
        assert p.percent_complete == 0.0

    def test_progress_after_update(self, database):
        from todo_app.models import TodoUpdate
        item = database.create(TodoCreate(title="A", description="a"))
        database.update(item.id, TodoUpdate(status="Completed"))
        p = database.get_progress()
        assert p.completed == 1
        assert p.percent_complete == 100.0

    def test_progress_rounding(self, database):
        """With 3 items and 1 completed, percent should be 33.3."""
        database.create(TodoCreate(title="A", description="a"))
        database.create(TodoCreate(title="B", description="b"))
        database.create(
            TodoCreate(title="C", description="c", status="Completed")
        )
        p = database.get_progress()
        assert p.percent_complete == pytest.approx(33.3, abs=0.1)

    def test_progress_after_reset(self, database):
        database.create(
            TodoCreate(title="A", description="a", status="Completed")
        )
        database.reset()
        p = database.get_progress()
        assert p.total == 0
        assert p.percent_complete == 0.0


# ---------------------------------------------------------------------------
# Integration tests for GET /todos/progress endpoint
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_db():
    """Reset the in-memory database before each test."""
    db.reset()
    yield
    db.reset()


@pytest.fixture
def client():
    return TestClient(app)


def _create_todo(
    client: TestClient,
    title: str = "Test",
    description: str = "Desc",
    completed: bool = False,
    status: str = "Not Started",
):
    return client.post(
        "/todos/",
        json={
            "title": title,
            "description": description,
            "completed": completed,
            "status": status,
        },
    )


class TestProgressEndpoint:
    """Tests for GET /todos/progress"""

    def test_progress_empty(self, client):
        resp = client.get("/todos/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["not_started"] == 0
        assert data["in_progress"] == 0
        assert data["completed"] == 0
        assert data["percent_complete"] == 0.0

    def test_progress_single_not_started(self, client):
        _create_todo(client, title="A", description="a")
        resp = client.get("/todos/progress")
        data = resp.json()
        assert data["total"] == 1
        assert data["not_started"] == 1
        assert data["percent_complete"] == 0.0

    def test_progress_single_completed(self, client):
        _create_todo(client, title="A", description="a", status="Completed")
        resp = client.get("/todos/progress")
        data = resp.json()
        assert data["total"] == 1
        assert data["completed"] == 1
        assert data["percent_complete"] == 100.0

    def test_progress_mixed(self, client):
        _create_todo(client, title="A", description="a", status="Not Started")
        _create_todo(client, title="B", description="b", status="In Progress")
        _create_todo(client, title="C", description="c", status="Completed")
        _create_todo(client, title="D", description="d", status="Completed")
        resp = client.get("/todos/progress")
        data = resp.json()
        assert data["total"] == 4
        assert data["not_started"] == 1
        assert data["in_progress"] == 1
        assert data["completed"] == 2
        assert data["percent_complete"] == 50.0

    def test_progress_after_status_update(self, client):
        resp = _create_todo(client, title="A", description="a")
        todo_id = resp.json()["id"]
        client.put(f"/todos/{todo_id}", json={"status": "Completed"})
        resp = client.get("/todos/progress")
        data = resp.json()
        assert data["completed"] == 1
        assert data["percent_complete"] == 100.0

    def test_progress_after_delete(self, client):
        _create_todo(client, title="A", description="a", status="Completed")
        resp = _create_todo(client, title="B", description="b")
        todo_id = resp.json()["id"]
        client.delete(f"/todos/{todo_id}")
        resp = client.get("/todos/progress")
        data = resp.json()
        assert data["total"] == 1
        assert data["completed"] == 1
        assert data["percent_complete"] == 100.0

    def test_progress_response_schema(self, client):
        resp = client.get("/todos/progress")
        data = resp.json()
        assert set(data.keys()) == {
            "total", "not_started", "in_progress", "completed", "percent_complete"
        }


class TestFrontendProgressUI:
    """Tests that the HTML frontend contains progress tracking elements."""

    def test_frontend_contains_progress_bar(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "progress-bar-fill" in resp.text
        assert "progress-bar-track" in resp.text

    def test_frontend_contains_progress_section(self, client):
        resp = client.get("/")
        assert "progressSection" in resp.text
        assert "Progress" in resp.text

    def test_frontend_contains_progress_stats(self, client):
        resp = client.get("/")
        assert "statNotStarted" in resp.text
        assert "statInProgress" in resp.text
        assert "statCompleted" in resp.text

    def test_frontend_contains_progress_percent(self, client):
        resp = client.get("/")
        assert "progressPercent" in resp.text

    def test_frontend_contains_checkboxes(self, client):
        resp = client.get("/")
        assert "complete-checkbox" in resp.text
        assert "toggleComplete" in resp.text

    def test_frontend_contains_filter_bar(self, client):
        resp = client.get("/")
        assert "filter-bar" in resp.text
        assert "filterBar" in resp.text

    def test_frontend_contains_status_options(self, client):
        resp = client.get("/")
        assert "Not Started" in resp.text
        assert "In Progress" in resp.text
        assert "Completed" in resp.text

    def test_frontend_calls_progress_api(self, client):
        resp = client.get("/")
        assert "/todos/progress" in resp.text

    def test_frontend_contains_aria_progressbar(self, client):
        resp = client.get("/")
        assert 'role="progressbar"' in resp.text
        assert "aria-valuenow" in resp.text
        assert "aria-valuemin" in resp.text
        assert "aria-valuemax" in resp.text


class TestToggleCompleteWorkflow:
    """End-to-end tests for the checkbox toggle-complete workflow."""

    def test_toggle_complete_marks_completed(self, client):
        resp = _create_todo(client, title="Task", description="Do it")
        todo_id = resp.json()["id"]
        assert resp.json()["status"] == "Not Started"

        # Simulate checkbox toggle -> mark completed
        resp = client.put(
            f"/todos/{todo_id}",
            json={"status": "Completed", "completed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "Completed"
        assert resp.json()["completed"] is True

        # Progress should reflect 100%
        resp = client.get("/todos/progress")
        assert resp.json()["percent_complete"] == 100.0

    def test_toggle_uncomplete_reverts_to_not_started(self, client):
        resp = _create_todo(
            client, title="Task", description="Done", status="Completed"
        )
        todo_id = resp.json()["id"]

        # Simulate unchecking
        resp = client.put(
            f"/todos/{todo_id}",
            json={"status": "Not Started", "completed": False},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "Not Started"
        assert resp.json()["completed"] is False

        resp = client.get("/todos/progress")
        assert resp.json()["percent_complete"] == 0.0

    def test_progress_updates_through_full_lifecycle(self, client):
        # Start with 2 items
        _create_todo(client, title="A", description="a")
        _create_todo(client, title="B", description="b")

        resp = client.get("/todos/progress")
        assert resp.json()["percent_complete"] == 0.0

        # Complete first item
        client.put("/todos/1", json={"status": "Completed", "completed": True})
        resp = client.get("/todos/progress")
        assert resp.json()["percent_complete"] == 50.0

        # Complete second item
        client.put("/todos/2", json={"status": "Completed", "completed": True})
        resp = client.get("/todos/progress")
        assert resp.json()["percent_complete"] == 100.0

        # Delete one
        client.delete("/todos/1")
        resp = client.get("/todos/progress")
        assert resp.json()["total"] == 1
        assert resp.json()["percent_complete"] == 100.0
