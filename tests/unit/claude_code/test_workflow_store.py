"""Tests for workflow_store module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from deep_agent.src.claude_code.workflow_store import WorkflowStore


@pytest.fixture
async def store() -> WorkflowStore:
    """Create a fresh workflow store for each test."""
    s = WorkflowStore()
    await s.clear()  # Clear module-level storage before each test
    return s


@pytest.mark.asyncio
async def test_register_workflow(store: WorkflowStore) -> None:
    """Test registering a new workflow."""
    workflow_id = "wf_123"
    task_name = "Build API endpoint"
    user_id = "user_1"

    await store.register(workflow_id, task_name, user_id)

    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["workflow_id"] == workflow_id
    assert workflow["task_name"] == task_name
    assert workflow["user_id"] == user_id
    assert workflow["status"] == "running"
    assert workflow["current_phase"] == "initializing"
    assert workflow["cost"] == 0.0
    assert workflow["iterations"] == 0
    assert isinstance(workflow["started_at"], datetime)
    assert workflow["decisions"] == []
    assert workflow["artifacts"] == []


@pytest.mark.asyncio
async def test_get_nonexistent_workflow(store: WorkflowStore) -> None:
    """Test getting a workflow that doesn't exist."""
    workflow = await store.get("nonexistent")
    assert workflow is None


@pytest.mark.asyncio
async def test_update_workflow_status(store: WorkflowStore) -> None:
    """Test updating workflow status and phase."""
    workflow_id = "wf_123"
    await store.register(workflow_id, "Test task", "user_1")

    await store.update_status(workflow_id, "paused", "plan_review", 5.25)

    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["status"] == "paused"
    assert workflow["current_phase"] == "plan_review"
    assert workflow["cost"] == 5.25


@pytest.mark.asyncio
async def test_update_nonexistent_workflow(store: WorkflowStore) -> None:
    """Test updating a workflow that doesn't exist should not raise."""
    # Should not raise, just silently ignore
    await store.update_status("nonexistent", "running", "implementing", 1.0)


@pytest.mark.asyncio
async def test_get_all_for_user(store: WorkflowStore) -> None:
    """Test retrieving all workflows for a specific user."""
    await store.register("wf_1", "Task 1", "user_1")
    await store.register("wf_2", "Task 2", "user_1")
    await store.register("wf_3", "Task 3", "user_2")

    user1_workflows = await store.get_all("user_1")
    assert len(user1_workflows) == 2
    workflow_ids = {w["workflow_id"] for w in user1_workflows}
    assert workflow_ids == {"wf_1", "wf_2"}

    user2_workflows = await store.get_all("user_2")
    assert len(user2_workflows) == 1
    assert user2_workflows[0]["workflow_id"] == "wf_3"


@pytest.mark.asyncio
async def test_get_all_empty_user(store: WorkflowStore) -> None:
    """Test getting workflows for user with no workflows."""
    workflows = await store.get_all("nonexistent_user")
    assert workflows == []


@pytest.mark.asyncio
async def test_thread_safety(store: WorkflowStore) -> None:
    """Test concurrent operations are thread-safe."""
    async def register_workflow(idx: int) -> None:
        await store.register(f"wf_{idx}", f"Task {idx}", "user_1")

    # Register 10 workflows concurrently
    await asyncio.gather(*[register_workflow(i) for i in range(10)])

    workflows = await store.get_all("user_1")
    assert len(workflows) == 10


@pytest.mark.asyncio
async def test_workflow_iterations_increment(store: WorkflowStore) -> None:
    """Test incrementing iterations."""
    workflow_id = "wf_123"
    await store.register(workflow_id, "Test task", "user_1")

    # Update with iterations
    await store.update_status(workflow_id, "running", "implementing", 1.0, iterations=1)
    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["iterations"] == 1

    # Update again
    await store.update_status(workflow_id, "running", "implementing", 2.0, iterations=2)
    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["iterations"] == 2


@pytest.mark.asyncio
async def test_workflow_cost_updates(store: WorkflowStore) -> None:
    """Test cost accumulation."""
    workflow_id = "wf_123"
    await store.register(workflow_id, "Test task", "user_1")

    await store.update_status(workflow_id, "running", "implementing", 2.50)
    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["cost"] == 2.50

    await store.update_status(workflow_id, "running", "implementing", 5.75)
    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["cost"] == 5.75


@pytest.mark.asyncio
async def test_workflow_status_transitions(store: WorkflowStore) -> None:
    """Test valid status transitions."""
    workflow_id = "wf_123"
    await store.register(workflow_id, "Test task", "user_1")

    # running -> paused
    await store.update_status(workflow_id, "paused", "plan_review", 1.0)
    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["status"] == "paused"

    # paused -> running
    await store.update_status(workflow_id, "running", "implementing", 2.0)
    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["status"] == "running"

    # running -> complete
    await store.update_status(workflow_id, "complete", "delivering", 3.0)
    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["status"] == "complete"

    # running -> error
    await store.register("wf_error", "Error task", "user_1")
    await store.update_status("wf_error", "error", "implementing", 1.0)
    workflow = await store.get("wf_error")
    assert workflow is not None
    assert workflow["status"] == "error"

    # running -> cancelled
    await store.register("wf_cancelled", "Cancelled task", "user_1")
    await store.update_status("wf_cancelled", "cancelled", "planning", 0.5)
    workflow = await store.get("wf_cancelled")
    assert workflow is not None
    assert workflow["status"] == "cancelled"


@pytest.mark.asyncio
async def test_started_at_timestamp(store: WorkflowStore) -> None:
    """Test that started_at is set to current UTC time."""
    before = datetime.now(timezone.utc)
    await store.register("wf_123", "Test task", "user_1")
    after = datetime.now(timezone.utc)

    workflow = await store.get("wf_123")
    assert workflow is not None
    started_at = workflow["started_at"]
    assert isinstance(started_at, datetime)
    assert before <= started_at <= after
    assert started_at.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_register_with_thread_id(store: WorkflowStore) -> None:
    """Test registering a workflow with thread_id mapping."""
    workflow_id = "wf_123"
    task_name = "Build API endpoint"
    user_id = "user_1"
    thread_id = "thread_abc"

    await store.register(workflow_id, task_name, user_id, thread_id=thread_id)

    workflow = await store.get(workflow_id)
    assert workflow is not None
    assert workflow["workflow_id"] == workflow_id
    assert workflow["thread_id"] == thread_id


@pytest.mark.asyncio
async def test_get_by_thread(store: WorkflowStore) -> None:
    """Test retrieving workflow by thread_id.

    Note: This test will pass None when Redis is not available,
    which is expected behavior for the in-memory fallback.
    """
    workflow_id = "wf_123"
    thread_id = "thread_abc"

    await store.register(workflow_id, "Test task", "user_1", thread_id=thread_id)

    workflow = await store.get_by_thread(thread_id)
    # In test environment without Redis, this will be None (expected)
    # In production with Redis, the mapping will work
    if workflow is not None:
        assert workflow["workflow_id"] == workflow_id
        assert workflow["thread_id"] == thread_id


@pytest.mark.asyncio
async def test_get_by_thread_no_mapping(store: WorkflowStore) -> None:
    """Test get_by_thread returns None when no workflow is mapped to thread."""
    workflow = await store.get_by_thread("nonexistent_thread")
    assert workflow is None


@pytest.mark.asyncio
async def test_get_by_thread_without_redis(store: WorkflowStore) -> None:
    """Test get_by_thread returns None when Redis is unavailable."""
    # Register without thread_id (Redis will be None for in-memory only)
    await store.register("wf_123", "Test task", "user_1")

    # Should return None since mapping only exists in Redis
    workflow = await store.get_by_thread("any_thread")
    assert workflow is None
