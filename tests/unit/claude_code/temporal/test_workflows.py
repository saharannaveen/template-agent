"""Tests for Temporal workflows."""

from __future__ import annotations

import pytest

# Skip all tests if temporalio is not installed
temporalio = pytest.importorskip("temporalio")

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from deep_agent.src.claude_code.temporal.workflows import LoopEngineeringWorkflow


@pytest.fixture
async def workflow_env():
    """Create test workflow environment."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.fixture
def mock_activities():
    """Create mock activities for testing."""
    return {
        "estimate_cost_activity": AsyncMock(return_value={
            "complexity": "medium",
            "estimated_cost_low": 1.5,
            "estimated_cost_high": 3.0,
            "max_possible_cost": 7.5,
        }),
        "run_claude_code_activity": AsyncMock(return_value={
            "output": "Tests passing",
            "session_id": "sess-123",
            "exit_code": 0,
            "is_error": False,
            "duration_seconds": 30.0,
            "test_passed": True,
            "test_signal": "output_pattern",
            "cost": 1.5,
            "input_tokens": 10000,
            "output_tokens": 5000,
            "model": "claude-opus-4-6",
        }),
        "notify_user_activity": AsyncMock(),
    }


async def test_workflow_completes_on_first_pass(workflow_env, mock_activities):
    """Test workflow completes successfully when tests pass on first try."""
    # Create worker with mock activities
    task_queue = "test-queue"
    worker = Worker(
        workflow_env.client,
        task_queue=task_queue,
        workflows=[LoopEngineeringWorkflow],
        activities=list(mock_activities.values()),
    )

    async with worker:
        # Start workflow
        handle = await workflow_env.client.start_workflow(
            LoopEngineeringWorkflow.run,
            {
                "prompt": "Build a simple feature",
                "workspace_path": "/tmp/workspace",
                "max_iterations": 5,
                "max_cost": 25.0,
            },
            id=f"test-workflow-{workflow_env.time_ns()}",
            task_queue=task_queue,
        )

        # Simulate user approving cost estimate
        await handle.signal(LoopEngineeringWorkflow.user_responds, {
            "action": "approve",
            "channel": "ui",
        })

        # Simulate user approving plan
        await handle.signal(LoopEngineeringWorkflow.user_responds, {
            "action": "approve",
            "channel": "ui",
        })

        # Simulate user accepting delivery
        await handle.signal(LoopEngineeringWorkflow.user_responds, {
            "action": "approve",
            "channel": "ui",
        })

        # Wait for completion
        result = await handle.result()

        assert result["status"] == "complete"
        assert result["iterations"] == 1
        assert result["cost"] > 0


async def test_workflow_retries_on_failure(workflow_env, mock_activities):
    """Test workflow retries when tests fail initially."""
    # Mock activity that fails twice then succeeds
    call_count = 0

    async def failing_activity(args):
        nonlocal call_count
        call_count += 1

        if call_count <= 2:
            # First two attempts fail
            return {
                "output": "Test failed: AssertionError",
                "session_id": f"sess-{call_count}",
                "exit_code": 1,
                "is_error": True,
                "duration_seconds": 30.0,
                "test_passed": False,
                "test_signal": "exit_code",
                "cost": 1.0,
                "input_tokens": 10000,
                "output_tokens": 5000,
                "model": "claude-opus-4-6",
            }
        else:
            # Third attempt succeeds
            return {
                "output": "Tests passing",
                "session_id": f"sess-{call_count}",
                "exit_code": 0,
                "is_error": False,
                "duration_seconds": 30.0,
                "test_passed": True,
                "test_signal": "output_pattern",
                "cost": 1.0,
                "input_tokens": 10000,
                "output_tokens": 5000,
                "model": "claude-opus-4-6",
            }

    mock_activities["run_claude_code_activity"] = failing_activity

    task_queue = "test-queue-2"
    worker = Worker(
        workflow_env.client,
        task_queue=task_queue,
        workflows=[LoopEngineeringWorkflow],
        activities=list(mock_activities.values()),
    )

    async with worker:
        handle = await workflow_env.client.start_workflow(
            LoopEngineeringWorkflow.run,
            {
                "prompt": "Build a feature that requires retries",
                "workspace_path": "/tmp/workspace",
                "max_iterations": 5,
                "max_cost": 25.0,
                "struggle_threshold": 3,
            },
            id=f"test-workflow-retry-{workflow_env.time_ns()}",
            task_queue=task_queue,
        )

        # Approve cost estimate
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "approve"})

        # Approve plan
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "approve"})

        # On third failure, we hit struggle threshold - user continues
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "continue"})

        # Accept delivery
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "approve"})

        result = await handle.result()

        assert result["status"] == "complete"
        assert result["iterations"] == 3


async def test_workflow_cost_circuit_breaker(workflow_env, mock_activities):
    """Test workflow aborts when cost exceeds budget."""
    # Mock activity that returns high cost
    async def expensive_activity(args):
        return {
            "output": "Test failed",
            "session_id": "sess-1",
            "exit_code": 1,
            "is_error": True,
            "duration_seconds": 30.0,
            "test_passed": False,
            "test_signal": "exit_code",
            "cost": 15.0,  # High cost per iteration
            "input_tokens": 100000,
            "output_tokens": 50000,
            "model": "claude-opus-4-6",
        }

    mock_activities["run_claude_code_activity"] = expensive_activity

    task_queue = "test-queue-3"
    worker = Worker(
        workflow_env.client,
        task_queue=task_queue,
        workflows=[LoopEngineeringWorkflow],
        activities=list(mock_activities.values()),
    )

    async with worker:
        handle = await workflow_env.client.start_workflow(
            LoopEngineeringWorkflow.run,
            {
                "prompt": "Expensive task",
                "workspace_path": "/tmp/workspace",
                "max_iterations": 5,
                "max_cost": 10.0,  # Low budget
            },
            id=f"test-workflow-cost-{workflow_env.time_ns()}",
            task_queue=task_queue,
        )

        # Approve cost estimate
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "approve"})

        # Approve plan
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "approve"})

        result = await handle.result()

        assert result["status"] == "cost_exceeded"
        assert result["cost"] > 10.0


async def test_workflow_cancelled_at_checkpoint(workflow_env, mock_activities):
    """Test workflow can be cancelled at any checkpoint."""
    task_queue = "test-queue-4"
    worker = Worker(
        workflow_env.client,
        task_queue=task_queue,
        workflows=[LoopEngineeringWorkflow],
        activities=list(mock_activities.values()),
    )

    async with worker:
        handle = await workflow_env.client.start_workflow(
            LoopEngineeringWorkflow.run,
            {
                "prompt": "Task to be cancelled",
                "workspace_path": "/tmp/workspace",
            },
            id=f"test-workflow-cancel-{workflow_env.time_ns()}",
            task_queue=task_queue,
        )

        # Approve cost estimate
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "approve"})

        # Cancel at plan review
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "cancel"})

        result = await handle.result()

        assert result["status"] == "cancelled"


async def test_workflow_status_query(workflow_env, mock_activities):
    """Test workflow status can be queried mid-execution."""
    task_queue = "test-queue-5"
    worker = Worker(
        workflow_env.client,
        task_queue=task_queue,
        workflows=[LoopEngineeringWorkflow],
        activities=list(mock_activities.values()),
    )

    async with worker:
        handle = await workflow_env.client.start_workflow(
            LoopEngineeringWorkflow.run,
            {
                "prompt": "Query test",
                "workspace_path": "/tmp/workspace",
            },
            id=f"test-workflow-query-{workflow_env.time_ns()}",
            task_queue=task_queue,
        )

        # Query status before any signals
        status = await handle.query(LoopEngineeringWorkflow.get_status)

        assert status["status"] == "estimating"
        assert status["cost"] == 0.0
        assert status["iteration"] == 0

        # Send approvals to complete workflow
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "approve"})
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "approve"})
        await handle.signal(LoopEngineeringWorkflow.user_responds, {"action": "approve"})

        await handle.result()

        # Query final status
        final_status = await handle.query(LoopEngineeringWorkflow.get_status)

        assert final_status["status"] == "delivering"
        assert final_status["cost"] > 0
