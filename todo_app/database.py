"""In-memory database for TODO items."""

from typing import Dict, Optional, List
from todo_app.models import TodoItem, TodoCreate, TodoUpdate, TodoProgress, TodoStatus


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
            status=todo_data.status,
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

    def get_progress(self) -> TodoProgress:
        """Calculate and return progress statistics across all TODO items."""
        todos = list(self._todos.values())
        total = len(todos)
        completed = sum(1 for t in todos if t.status == TodoStatus.COMPLETED)
        in_progress = sum(1 for t in todos if t.status == TodoStatus.IN_PROGRESS)
        not_started = sum(1 for t in todos if t.status == TodoStatus.NOT_STARTED)
        percent_complete = round((completed / total) * 100, 1) if total > 0 else 0.0
        return TodoProgress(
            total=total,
            not_started=not_started,
            in_progress=in_progress,
            completed=completed,
            percent_complete=percent_complete,
        )

    def reset(self) -> None:
        """Clear all data (useful for testing)."""
        self._todos.clear()
        self._counter = 0
