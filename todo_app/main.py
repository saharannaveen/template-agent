"""FastAPI application for the TODO list."""

from fastapi import FastAPI, HTTPException
from typing import List

from todo_app.models import TodoCreate, TodoUpdate, TodoItem
from todo_app.database import TodoDatabase

app = FastAPI(
    title="TODO App",
    description="A simple TODO list API built with FastAPI.",
    version="1.0.0",
)

db = TodoDatabase()


@app.post("/todos/", response_model=TodoItem, status_code=201)
def create_todo(todo: TodoCreate) -> TodoItem:
    """Create a new TODO item."""
    return db.create(todo)


@app.get("/todos/", response_model=List[TodoItem])
def get_todos() -> List[TodoItem]:
    """Get a list of all TODO items."""
    return db.get_all()


@app.get("/todos/{todo_id}", response_model=TodoItem)
def get_todo(todo_id: int) -> TodoItem:
    """Get a single TODO item by its ID."""
    todo = db.get_by_id(todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="TODO item not found")
    return todo


@app.put("/todos/{todo_id}", response_model=TodoItem)
def update_todo(todo_id: int, todo_data: TodoUpdate) -> TodoItem:
    """Update a TODO item."""
    todo = db.update(todo_id, todo_data)
    if todo is None:
        raise HTTPException(status_code=404, detail="TODO item not found")
    return todo


@app.delete("/todos/{todo_id}", response_model=TodoItem)
def delete_todo(todo_id: int) -> TodoItem:
    """Delete a TODO item."""
    todo = db.delete(todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="TODO item not found")
    return todo
