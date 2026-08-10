"""Integration tests for FastAPI endpoints using TestClient."""

import pytest
from fastapi.testclient import TestClient

from todo_app.main import app, db
from todo_app.models import TodoStatus


@pytest.fixture(autouse=True)
def reset_db():
    """Reset the in-memory database before each test."""
    db.reset()
    yield
    db.reset()


@pytest.fixture
def client():
    """Provide a TestClient instance."""
    return TestClient(app)


def _create_todo(
    client: TestClient,
    title: str = "Test",
    description: str = "Desc",
    completed: bool = False,
    status: str = "Not Started",
):
    """Helper to create a TODO item and return the response."""
    return client.post(
        "/todos/",
        json={
            "title": title,
            "description": description,
            "completed": completed,
            "status": status,
        },
    )


class TestCreateTodo:
    """Tests for POST /todos/"""

    def test_create_todo_success(self, client):
        resp = _create_todo(client, title="Buy groceries", description="Milk, eggs, bread")
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == 1
        assert data["title"] == "Buy groceries"
        assert data["description"] == "Milk, eggs, bread"
        assert data["completed"] is False
        assert data["status"] == "Not Started"

    def test_create_todo_with_completed_true(self, client):
        resp = _create_todo(client, title="Done task", description="Already done", completed=True)
        assert resp.status_code == 201
        assert resp.json()["completed"] is True

    def test_create_todo_auto_increment_ids(self, client):
        resp1 = _create_todo(client, title="First", description="1")
        resp2 = _create_todo(client, title="Second", description="2")
        assert resp1.json()["id"] == 1
        assert resp2.json()["id"] == 2

    def test_create_todo_missing_title(self, client):
        resp = client.post("/todos/", json={"description": "No title"})
        assert resp.status_code == 422

    def test_create_todo_missing_description(self, client):
        resp = client.post("/todos/", json={"title": "No desc"})
        assert resp.status_code == 422

    def test_create_todo_empty_body(self, client):
        resp = client.post("/todos/", json={})
        assert resp.status_code == 422

    def test_create_todo_with_status_in_progress(self, client):
        resp = _create_todo(client, title="WIP", description="D", status="In Progress")
        assert resp.status_code == 201
        assert resp.json()["status"] == "In Progress"

    def test_create_todo_with_status_completed(self, client):
        resp = _create_todo(client, title="Done", description="D", status="Completed")
        assert resp.status_code == 201
        assert resp.json()["status"] == "Completed"

    def test_create_todo_with_invalid_status(self, client):
        resp = client.post(
            "/todos/",
            json={"title": "T", "description": "D", "status": "InvalidStatus"},
        )
        assert resp.status_code == 422


class TestGetTodos:
    """Tests for GET /todos/"""

    def test_get_todos_empty(self, client):
        resp = client.get("/todos/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_todos_returns_all(self, client):
        _create_todo(client, title="A", description="a")
        _create_todo(client, title="B", description="b")
        resp = client.get("/todos/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["title"] == "A"
        assert data[1]["title"] == "B"

    def test_get_todos_includes_status(self, client):
        _create_todo(client, title="A", description="a", status="In Progress")
        resp = client.get("/todos/")
        assert resp.json()[0]["status"] == "In Progress"


class TestGetTodoById:
    """Tests for GET /todos/{todo_id}"""

    def test_get_todo_found(self, client):
        create_resp = _create_todo(client, title="Find me", description="Here")
        todo_id = create_resp.json()["id"]
        resp = client.get(f"/todos/{todo_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Find me"

    def test_get_todo_not_found(self, client):
        resp = client.get("/todos/999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "TODO item not found"

    def test_get_todo_includes_status(self, client):
        create_resp = _create_todo(
            client, title="T", description="D", status="Completed"
        )
        todo_id = create_resp.json()["id"]
        resp = client.get(f"/todos/{todo_id}")
        assert resp.json()["status"] == "Completed"


class TestUpdateTodo:
    """Tests for PUT /todos/{todo_id}"""

    def test_update_title(self, client):
        create_resp = _create_todo(client, title="Old", description="Desc")
        todo_id = create_resp.json()["id"]
        resp = client.put(f"/todos/{todo_id}", json={"title": "New"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New"
        assert resp.json()["description"] == "Desc"  # unchanged

    def test_update_description(self, client):
        create_resp = _create_todo(client, title="T", description="Old desc")
        todo_id = create_resp.json()["id"]
        resp = client.put(f"/todos/{todo_id}", json={"description": "New desc"})
        assert resp.status_code == 200
        assert resp.json()["description"] == "New desc"

    def test_update_completed(self, client):
        create_resp = _create_todo(client, title="T", description="D")
        todo_id = create_resp.json()["id"]
        resp = client.put(f"/todos/{todo_id}", json={"completed": True})
        assert resp.status_code == 200
        assert resp.json()["completed"] is True

    def test_update_all_fields(self, client):
        create_resp = _create_todo(client, title="T", description="D")
        todo_id = create_resp.json()["id"]
        resp = client.put(
            f"/todos/{todo_id}",
            json={"title": "Updated", "description": "Updated Desc", "completed": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated"
        assert data["description"] == "Updated Desc"
        assert data["completed"] is True

    def test_update_no_fields(self, client):
        create_resp = _create_todo(client, title="T", description="D")
        todo_id = create_resp.json()["id"]
        resp = client.put(f"/todos/{todo_id}", json={})
        assert resp.status_code == 200
        # Nothing changes
        assert resp.json()["title"] == "T"

    def test_update_not_found(self, client):
        resp = client.put("/todos/999", json={"title": "X"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "TODO item not found"

    def test_update_status_to_in_progress(self, client):
        create_resp = _create_todo(client, title="T", description="D")
        todo_id = create_resp.json()["id"]
        resp = client.put(f"/todos/{todo_id}", json={"status": "In Progress"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "In Progress"

    def test_update_status_to_completed(self, client):
        create_resp = _create_todo(client, title="T", description="D")
        todo_id = create_resp.json()["id"]
        resp = client.put(f"/todos/{todo_id}", json={"status": "Completed"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "Completed"

    def test_update_status_to_not_started(self, client):
        create_resp = _create_todo(
            client, title="T", description="D", status="Completed"
        )
        todo_id = create_resp.json()["id"]
        resp = client.put(f"/todos/{todo_id}", json={"status": "Not Started"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "Not Started"

    def test_update_status_invalid_value(self, client):
        create_resp = _create_todo(client, title="T", description="D")
        todo_id = create_resp.json()["id"]
        resp = client.put(f"/todos/{todo_id}", json={"status": "InvalidStatus"})
        assert resp.status_code == 422

    def test_update_status_preserves_other_fields(self, client):
        create_resp = _create_todo(client, title="T", description="D")
        todo_id = create_resp.json()["id"]
        resp = client.put(f"/todos/{todo_id}", json={"status": "In Progress"})
        data = resp.json()
        assert data["title"] == "T"
        assert data["description"] == "D"
        assert data["completed"] is False
        assert data["status"] == "In Progress"


class TestDeleteTodo:
    """Tests for DELETE /todos/{todo_id}"""

    def test_delete_success(self, client):
        create_resp = _create_todo(client, title="Delete me", description="Gone")
        todo_id = create_resp.json()["id"]
        resp = client.delete(f"/todos/{todo_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Delete me"
        # Verify it's actually deleted
        get_resp = client.get(f"/todos/{todo_id}")
        assert get_resp.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/todos/999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "TODO item not found"

    def test_delete_then_list(self, client):
        _create_todo(client, title="A", description="a")
        create_resp = _create_todo(client, title="B", description="b")
        todo_id = create_resp.json()["id"]
        client.delete(f"/todos/{todo_id}")
        resp = client.get("/todos/")
        assert len(resp.json()) == 1
        assert resp.json()[0]["title"] == "A"


class TestFrontend:
    """Tests for the HTML frontend endpoint."""

    def test_frontend_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "TODO App" in resp.text

    def test_frontend_contains_status_options(self, client):
        resp = client.get("/")
        assert "Not Started" in resp.text
        assert "In Progress" in resp.text
        assert "Completed" in resp.text


class TestEndToEndWorkflow:
    """End-to-end workflow test combining multiple operations."""

    def test_full_crud_workflow(self, client):
        # Create
        resp = _create_todo(client, title="Workout", description="Go to gym")
        assert resp.status_code == 201
        todo_id = resp.json()["id"]

        # Read single
        resp = client.get(f"/todos/{todo_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Workout"

        # Read all
        resp = client.get("/todos/")
        assert len(resp.json()) == 1

        # Update
        resp = client.put(f"/todos/{todo_id}", json={"completed": True})
        assert resp.status_code == 200
        assert resp.json()["completed"] is True

        # Delete
        resp = client.delete(f"/todos/{todo_id}")
        assert resp.status_code == 200

        # Verify gone
        resp = client.get(f"/todos/{todo_id}")
        assert resp.status_code == 404

        resp = client.get("/todos/")
        assert resp.json() == []

    def test_full_status_workflow(self, client):
        """Test the complete lifecycle of status transitions."""
        # Create with default status
        resp = _create_todo(client, title="Feature", description="Build it")
        assert resp.status_code == 201
        todo_id = resp.json()["id"]
        assert resp.json()["status"] == "Not Started"

        # Transition to In Progress
        resp = client.put(f"/todos/{todo_id}", json={"status": "In Progress"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "In Progress"

        # Transition to Completed
        resp = client.put(
            f"/todos/{todo_id}",
            json={"status": "Completed", "completed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "Completed"
        assert resp.json()["completed"] is True

        # Verify via GET
        resp = client.get(f"/todos/{todo_id}")
        assert resp.json()["status"] == "Completed"

        # Revert back to Not Started
        resp = client.put(
            f"/todos/{todo_id}",
            json={"status": "Not Started", "completed": False},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "Not Started"
        assert resp.json()["completed"] is False
