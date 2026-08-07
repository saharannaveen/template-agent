"""In-memory database for TODO items."""

from typing import Dict, Optional, List
from todo_app.models import TodoItem, TodoCreate, TodoUpdate


class TodoDatabase:
    """Simple in-memory database for storing TODO items."""

    def __init__(self) -> None:
        self._todos: Dict[int, TodoItem] = {}
        self._counter: int = 0

    def _next_id(self) -> int:
        """Generate the next auto-incrementing ID."""
        self._counter += 1
        return self._counter

    def create(self, todo_data: TodoCreate) -> TodoItem:
        """Create a new TODO item and return it."""
        todo_id = self._next_id()
        todo = TodoItem(
            id=todo_id,
            title=todo_data.title,
            description=todo_data.description,
            completed=todo_data.completed,
        )
        self._todos[todo_id] = todo
        return todo

    def get_all(self) -> List[TodoItem]:
        """Return all TODO items."""
        return list(self._todos.values())

    def get_by_id(self, todo_id: int) -> Optional[TodoItem]:
        """Return a TODO item by its ID, or None if not found."""
        return self._todos.get(todo_id)

    def update(self, todo_id: int, todo_data: TodoUpdate) -> Optional[TodoItem]:
        """Update a TODO item. Returns updated item or None if not found."""
        existing = self._todos.get(todo_id)
        if existing is None:
            return None

        update_fields = todo_data.model_dump(exclude_unset=True)
        updated = existing.model_copy(update=update_fields)
        self._todos[todo_id] = updated
        return updated

    def delete(self, todo_id: int) -> Optional[TodoItem]:
        """Delete a TODO item. Returns deleted item or None if not found."""
        return self._todos.pop(todo_id, None)

    def reset(self) -> None:
        """Clear all data (useful for testing)."""
        self._todos.clear()
        self._counter = 0
