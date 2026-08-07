"""Pydantic models for the TODO application."""

from pydantic import BaseModel
from typing import Optional


class TodoCreate(BaseModel):
    """Schema for creating a new TODO item."""
    title: str
    description: str
    completed: bool = False


class TodoUpdate(BaseModel):
    """Schema for updating an existing TODO item. All fields are optional."""
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None


class TodoItem(BaseModel):
    """Schema representing a TODO item stored in the database."""
    id: int
    title: str
    description: str
    completed: bool = False
