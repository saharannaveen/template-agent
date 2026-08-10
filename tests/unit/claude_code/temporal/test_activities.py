"""Tests for Temporal activities."""

from __future__ import annotations

import pytest

# Skip all tests if temporalio is not installed
pytest.importorskip("temporalio")

from unittest.mock import AsyncMock, MagicMock, patch

from deep_agent.src.claude_code.temporal.activities import (
    estimate_cost_activity,
    notify_user_activity,
    run_claude_code_activity,
)


@pytest.mark.asyncio
async def test_estimate_cost_activity():
    """Test cost estimation activity wraps Phase 1 estimator correctly."""
    task = {
        "prompt": "Build a shipping calculator API with tests",
        "max_iterations": 5,
    }

    result = await estimate_cost_activity(task)

    assert "complexity" in result
    assert "estimated_cost_low" in result
    assert "estimated_cost_high" in result
    assert "max_possible_cost" in result
    assert result["complexity"] in ["trivial", "simple", "medium", "complex"]


@pytest.mark.asyncio
async def test_estimate_cost_activity_with_custom_pricing():
    """Test cost estimation with custom pricing."""
    task = {
        "prompt": "Simple task",
        "max_iterations": 3,
        "pricing": {
            "claude-sonnet-4-5": {
                "input_per_mtok": 3.0,
                "output_per_mtok": 15.0,
            },
        },
    }

    result = await estimate_cost_activity(task)

    # Should use custom pricing
    assert result["complexity"] == "medium"
    assert result["estimated_cost_low"] > 0


@pytest.mark.asyncio
async def test_run_claude_code_activity_success():
    """Test Claude Code activity wraps runner correctly on success."""
    with patch("deep_agent.src.claude_code.temporal.activities.PodmanClaudeCodeRunner") as MockRunner:
        # Mock successful execution
        mock_result = MagicMock()
        mock_result.output = "All tests passing"
        mock_result.session_id = "sess-123"
        mock_result.exit_code = 0
        mock_result.is_error = False
        mock_result.duration_seconds = 30.0
        mock_result.input_tokens = 10000
        mock_result.output_tokens = 5000
        mock_result.cache_read_tokens = 0
        mock_result.cache_creation_tokens = 0
        mock_result.model = "claude-opus-4-6"
        mock_result.compute_cost.return_value = 1.5
        mock_result.test_result = MagicMock(
            passed=True,
            signal="output_pattern",
            details="Pass markers found",
        )

        mock_runner = MockRunner.return_value
        mock_runner.execute = AsyncMock(return_value=mock_result)

        args = {
            "prompt": "Implement feature",
            "workspace_path": "/tmp/workspace",
            "task_type": "implementation",
        }

        result = await run_claude_code_activity(args)

        assert result["output"] == "All tests passing"
        assert result["session_id"] == "sess-123"
        assert result["exit_code"] == 0
        assert result["test_passed"] is True
        assert result["cost"] == 1.5

        # Verify runner was called correctly
        mock_runner.execute.assert_called_once_with(
            prompt="Implement feature",
            workspace_path="/tmp/workspace",
            allowed_tools=None,
            session_id=None,
            task_type="implementation",
        )


@pytest.mark.asyncio
async def test_run_claude_code_activity_failure():
    """Test Claude Code activity handles failures correctly."""
    with patch("deep_agent.src.claude_code.temporal.activities.PodmanClaudeCodeRunner") as MockRunner:
        # Mock failed execution
        mock_result = MagicMock()
        mock_result.output = "Test failed: AssertionError"
        mock_result.session_id = "sess-456"
        mock_result.exit_code = 1
        mock_result.is_error = True
        mock_result.duration_seconds = 25.0
        mock_result.input_tokens = 8000
        mock_result.output_tokens = 3000
        mock_result.cache_read_tokens = 0
        mock_result.cache_creation_tokens = 0
        mock_result.model = "claude-opus-4-6"
        mock_result.compute_cost.return_value = 1.0
        mock_result.test_result = MagicMock(
            passed=False,
            signal="exit_code",
            details="Non-zero exit code",
        )

        mock_runner = MockRunner.return_value
        mock_runner.execute = AsyncMock(return_value=mock_result)

        args = {
            "prompt": "Implement feature",
            "workspace_path": "/tmp/workspace",
        }

        result = await run_claude_code_activity(args)

        assert result["exit_code"] == 1
        assert result["test_passed"] is False
        assert result["test_signal"] == "exit_code"


@pytest.mark.asyncio
async def test_run_claude_code_activity_with_session_resume():
    """Test Claude Code activity can resume sessions."""
    with patch("deep_agent.src.claude_code.temporal.activities.PodmanClaudeCodeRunner") as MockRunner:
        mock_result = MagicMock()
        mock_result.output = "Resumed and fixed"
        mock_result.session_id = "sess-789"
        mock_result.exit_code = 0
        mock_result.is_error = False
        mock_result.duration_seconds = 20.0
        mock_result.input_tokens = 5000
        mock_result.output_tokens = 2000
        mock_result.cache_read_tokens = 0
        mock_result.cache_creation_tokens = 0
        mock_result.model = "claude-opus-4-6"
        mock_result.compute_cost.return_value = 0.8
        mock_result.test_result = MagicMock(passed=True, signal="output_pattern", details="OK")

        mock_runner = MockRunner.return_value
        mock_runner.execute = AsyncMock(return_value=mock_result)

        args = {
            "prompt": "Fix the error",
            "workspace_path": "/tmp/workspace",
            "session_id": "sess-prev",
        }

        result = await run_claude_code_activity(args)

        # Verify session_id was passed through
        mock_runner.execute.assert_called_once_with(
            prompt="Fix the error",
            workspace_path="/tmp/workspace",
            allowed_tools=None,
            session_id="sess-prev",
            task_type=None,
        )


@pytest.mark.asyncio
async def test_notify_user_activity():
    """Test user notification activity logs correctly."""
    # This is a placeholder - real implementation would test notification routing
    await notify_user_activity(
        event_type="plan_review",
        data={"plan": "Step 1\nStep 2\nStep 3"},
        cumulative_cost=1.5,
    )

    # Should not raise - just logs for now
    # In production, would verify:
    # - SSE event sent to Redis
    # - Slack message posted
    # - Email sent
    # - Webhook called
