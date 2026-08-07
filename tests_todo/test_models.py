"""Unit tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from todo_app.models import TodoCreate, TodoUpdate, TodoItem


class TestTodoCreate:
    """Tests for the TodoCreate model."""

    def test_create_with_all_fields(self):
        todo = TodoCreate(title="Test", description="A test todo", completed=True)
        assert todo.title == "Test"
        assert todo.description == "A test todo"
        assert todo.completed is True

    def test_create_defaults_completed_to_false(self):
        todo = TodoCreate(title="Test", description="A test todo")
        assert todo.completed is False

    def test_create_missing_title_raises(self):
        with pytest.raises(ValidationError):
            TodoCreate(description="No title")

    def test_create_missing_description_raises(self):
        with pytest.raises(ValidationError):
            TodoCreate(title="No desc")

    def test_create_empty_strings_allowed(self):
        todo = TodoCreate(title="", description="")
        assert todo.title == ""
        assert todo.description == ""

    def test_create_from_dict(self):
        data = {"title": "Buy milk", "description": "From the store"}
        todo = TodoCreate(**data)
        assert todo.title == "Buy milk"
        assert todo.description == "From the store"
        assert todo.completed is False


class TestTodoUpdate:
    """Tests for the TodoUpdate model."""

    def test_update_all_fields(self):
        update = TodoUpdate(title="New", description="Updated", completed=True)
        assert update.title == "New"
        assert update.description == "Updated"
        assert update.completed is True

    def test_update_partial_title_only(self):
        update = TodoUpdate(title="New Title")
        assert update.title == "New Title"
        assert update.description is None
        assert update.completed is None

    def test_update_partial_completed_only(self):
        update = TodoUpdate(completed=True)
        assert update.completed is True
        assert update.title is None
        assert update.description is None

    def test_update_no_fields(self):
        update = TodoUpdate()
        assert update.title is None
        assert update.description is None
        assert update.completed is None

    def test_update_exclude_unset(self):
        update = TodoUpdate(title="Only title")
        dumped = update.model_dump(exclude_unset=True)
        assert dumped == {"title": "Only title"}

    def test_update_exclude_unset_empty(self):
        update = TodoUpdate()
        dumped = update.model_dump(exclude_unset=True)
        assert dumped == {}


class TestTodoItem:
    """Tests for the TodoItem model."""

    def test_item_all_fields(self):
        item = TodoItem(id=1, title="Test", description="Desc", completed=True)
        assert item.id == 1
        assert item.title == "Test"
        assert item.description == "Desc"
        assert item.completed is True

    def test_item_defaults_completed_to_false(self):
        item = TodoItem(id=1, title="Test", description="Desc")
        assert item.completed is False

    def test_item_missing_id_raises(self):
        with pytest.raises(ValidationError):
            TodoItem(title="Test", description="Desc")

    def test_item_missing_title_raises(self):
        with pytest.raises(ValidationError):
            TodoItem(id=1, description="Desc")

    def test_item_missing_description_raises(self):
        with pytest.raises(ValidationError):
            TodoItem(id=1, title="Test")

    def test_item_serialization(self):
        item = TodoItem(id=1, title="Test", description="Desc", completed=False)
        data = item.model_dump()
        assert data == {
            "id": 1,
            "title": "Test",
            "description": "Desc",
            "completed": False,
        }

    def test_item_model_copy_with_update(self):
        item = TodoItem(id=1, title="Old", description="Old desc", completed=False)
        updated = item.model_copy(update={"title": "New", "completed": True})
        assert updated.id == 1
        assert updated.title == "New"
        assert updated.description == "Old desc"
        assert updated.completed is True
