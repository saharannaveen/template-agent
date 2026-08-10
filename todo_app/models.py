"""Pydantic models for the TODO application."""

from enum import Enum

from pydantic import BaseModel
from typing import Optional


class TodoStatus(str, Enum):
    """Possible status values for a TODO item."""
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"


class TodoCreate(BaseModel):
    """Schema for creating a new TODO item."""
    title: str
    description: str
    completed: bool = False
    status: TodoStatus = TodoStatus.NOT_STARTED


class TodoUpdate(BaseModel):
    """Schema for updating an existing TODO item. All fields are optional."""
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None
    status: Optional[TodoStatus] = None


class TodoItem(BaseModel):
    """Schema representing a TODO item stored in the database."""
    id: int
    title: str
    description: str
    completed: bool = False
    status: TodoStatus = TodoStatus.NOT_STARTED


class TodoProgress(BaseModel):
    """Schema representing overall progress across all TODO items."""
    total: int
    not_started: int
    in_progress: int
    completed: int
    percent_complete: float
