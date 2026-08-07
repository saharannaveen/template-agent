"""Unit tests for the in-memory database."""

import pytest
from todo_app.database import TodoDatabase
from todo_app.models import TodoCreate, TodoUpdate


@pytest.fixture
def db():
    """Provide a fresh database for each test."""
    return TodoDatabase()


class TestTodoDatabase:
    """Tests for TodoDatabase operations."""

    def test_create_returns_item_with_id(self, db):
        item = db.create(TodoCreate(title="Test", description="Desc"))
        assert item.id == 1
        assert item.title == "Test"
        assert item.description == "Desc"
        assert item.completed is False

    def test_create_auto_increments_id(self, db):
        item1 = db.create(TodoCreate(title="First", description="1"))
        item2 = db.create(TodoCreate(title="Second", description="2"))
        assert item1.id == 1
        assert item2.id == 2

    def test_get_all_empty(self, db):
        assert db.get_all() == []

    def test_get_all_returns_all(self, db):
        db.create(TodoCreate(title="A", description="a"))
        db.create(TodoCreate(title="B", description="b"))
        items = db.get_all()
        assert len(items) == 2

    def test_get_by_id_found(self, db):
        created = db.create(TodoCreate(title="Test", description="Desc"))
        found = db.get_by_id(created.id)
        assert found is not None
        assert found.id == created.id

    def test_get_by_id_not_found(self, db):
        assert db.get_by_id(999) is None

    def test_update_existing(self, db):
        created = db.create(TodoCreate(title="Old", description="Old desc"))
        updated = db.update(created.id, TodoUpdate(title="New"))
        assert updated is not None
        assert updated.title == "New"
        assert updated.description == "Old desc"  # unchanged

    def test_update_non_existing(self, db):
        result = db.update(999, TodoUpdate(title="X"))
        assert result is None

    def test_update_completed_field(self, db):
        created = db.create(TodoCreate(title="Task", description="D"))
        updated = db.update(created.id, TodoUpdate(completed=True))
        assert updated is not None
        assert updated.completed is True

    def test_delete_existing(self, db):
        created = db.create(TodoCreate(title="Del", description="D"))
        deleted = db.delete(created.id)
        assert deleted is not None
        assert deleted.id == created.id
        assert db.get_by_id(created.id) is None

    def test_delete_non_existing(self, db):
        assert db.delete(999) is None

    def test_reset(self, db):
        db.create(TodoCreate(title="A", description="a"))
        db.reset()
        assert db.get_all() == []
        new_item = db.create(TodoCreate(title="B", description="b"))
        assert new_item.id == 1  # counter reset
