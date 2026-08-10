"""Tests for LoopEngineeringMiddleware."""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from deep_agent.src.claude_code.config import (
    ClaudeCodeCostConfig,
    LoopEngineeringConfig,
)
from deep_agent.src.claude_code.runner import ClaudeCodeResult


def _make_tool_message(
    output: str,
    session_id: str = "session123",
    exit_code: int = 0,
    is_error: bool = False,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    model: str = "claude-opus-4-6",
    tool_call_id: str = "tc1",
) -> ToolMessage:
    """Helper to create a ToolMessage with claude_code_result."""
    result = ClaudeCodeResult(
        output=output,
        session_id=session_id,
        exit_code=exit_code,
        is_error=is_error,
        duration_seconds=2.5,
        raw_json={},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        model=model,
    )
    return ToolMessage(
        content=output,
        tool_call_id=tool_call_id,
        additional_kwargs={"claude_code_result": asdict(result)},
    )


class TestLoopMiddlewarePassthrough:
    """Test that non-claude_code tools pass through without looping."""

    async def test_passthrough_non_claude_code_tool(self):
        """Test awrap_tool_call passes through non-claude_code tools."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=5)
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        request = MagicMock()
        request.tool_call = {"name": "search_web", "args": {}, "id": "tc1"}
        handler = AsyncMock(return_value=MagicMock())

        await mw.awrap_tool_call(request, handler)
        handler.assert_called_once_with(request)


class TestLoopMiddlewareSelfCorrection:
    """Test self-correction loop logic."""

    async def test_returns_on_first_success(self):
        """Test loop exits after first successful result."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=5)
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # Handler returns passing result
        passing_msg = _make_tool_message(output="All tests passed!", exit_code=0)
        handler = AsyncMock(return_value=passing_msg)

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Fix bug"},
            "id": "tc1",
        }

        result = await mw.awrap_tool_call(request, handler)

        # Handler called exactly once
        handler.assert_called_once()
        assert isinstance(result, ToolMessage)
        assert "All tests passed!" in result.content

    async def test_retries_on_failure_then_succeeds(self):
        """Test loop retries on failure, then succeeds on second try."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=5)
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # First call fails, second succeeds
        fail_msg = _make_tool_message(
            output="Test failed: AssertionError in test_foo", exit_code=1
        )
        pass_msg = _make_tool_message(
            output="All tests passed!", exit_code=0, session_id="session123"
        )

        handler = AsyncMock(side_effect=[fail_msg, pass_msg])

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Fix bug"},
            "id": "tc1",
        }

        result = await mw.awrap_tool_call(request, handler)

        # Handler called twice
        assert handler.call_count == 2
        assert isinstance(result, ToolMessage)
        assert "All tests passed!" in result.content

    async def test_exhausts_max_iterations(self):
        """Test loop exhausts max_iterations when handler always fails."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=2)
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # Always returns fail
        fail_msg = _make_tool_message(output="Test failed: error", exit_code=1)
        handler = AsyncMock(return_value=fail_msg)

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Fix bug"},
            "id": "tc1",
        }

        result = await mw.awrap_tool_call(request, handler)

        # Handler called exactly max_iterations times
        assert handler.call_count == 2
        assert isinstance(result, ToolMessage)

    async def test_cost_circuit_breaker(self):
        """Test loop aborts when cost limit exceeded."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=5)
        # Set low cost limit (minimum allowed is 1.0)
        cost_config = ClaudeCodeCostConfig(max_cost_usd_per_loop=1.0)
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # Handler returns fail with high token usage that exceeds $1.0 limit
        # Cost: (100000/1M)*15 + (100000/1M)*75 = 1.5 + 7.5 = 9.0 USD > 1.0
        fail_msg = _make_tool_message(
            output="Test failed: error",
            exit_code=1,
            input_tokens=100_000,
            output_tokens=100_000,
        )
        handler = AsyncMock(return_value=fail_msg)

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Fix bug"},
            "id": "tc1",
        }

        result = await mw.awrap_tool_call(request, handler)

        # Handler called once, then aborted
        assert handler.call_count == 1
        assert isinstance(result, ToolMessage)
        assert "cost limit exceeded" in result.content.lower()

    async def test_session_reuse_cap(self):
        """Test session_id reset after max_session_reuse_iterations."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(
            enabled=True, max_iterations=5, max_session_reuse_iterations=2
        )
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # Handler returns fail 3 times, then success
        fail_msg = _make_tool_message(
            output="Test failed: error", exit_code=1, session_id="session123"
        )
        pass_msg = _make_tool_message(
            output="All tests passed!", exit_code=0, session_id="session456"
        )

        handler = AsyncMock(side_effect=[fail_msg, fail_msg, fail_msg, pass_msg])

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Fix bug"},
            "id": "tc1",
        }

        result = await mw.awrap_tool_call(request, handler)

        # Handler called 4 times
        assert handler.call_count == 4

        # Check the third call (iteration 3) - session_id should be None (reset)
        third_call = handler.call_args_list[2]
        third_request = third_call[0][0]
        assert third_request.tool_call["args"]["session_id"] is None


class TestLoopMiddlewareUseCases:
    """Test real-world use case scenarios."""

    async def test_usecase_simple_bug_fix(self):
        """Simple bug fix passes first try, low cost."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=5)
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # Direct pass with low tokens
        pass_msg = _make_tool_message(
            output="Fixed the typo in config.py - all tests passed!",
            exit_code=0,
            input_tokens=500,
            output_tokens=200,
        )
        handler = AsyncMock(return_value=pass_msg)

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Fix the typo in config.py"},
            "id": "tc1",
        }

        result = await mw.awrap_tool_call(request, handler)

        # One call, success
        handler.assert_called_once()
        assert isinstance(result, ToolMessage)
        assert "Fixed the typo" in result.content

    async def test_usecase_feature_with_retry(self):
        """Feature fails once (test failure), retries with error context, passes."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=5)
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # First: test failure
        fail_msg = _make_tool_message(
            output=(
                "Built shipping calculator.\n"
                "Tests failed:\n"
                "FAILED test_shipping.py::test_calculate_rate - AssertionError: expected 10.5 got 15.0"
            ),
            exit_code=1,
            session_id="session123",
        )
        # Second: success
        pass_msg = _make_tool_message(
            output="Fixed rate calculation - all tests passed!",
            exit_code=0,
            session_id="session123",
        )

        handler = AsyncMock(side_effect=[fail_msg, pass_msg])

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Build shipping calculator with tests"},
            "id": "tc1",
        }

        result = await mw.awrap_tool_call(request, handler)

        # Two calls
        assert handler.call_count == 2
        assert isinstance(result, ToolMessage)
        assert "all tests passed!" in result.content

        # Second call should have error context prepended (session_id exists, so just error_context)
        second_call = handler.call_args_list[1]
        second_request = second_call[0][0]
        second_prompt = second_request.tool_call["args"]["prompt"]
        # Should contain error context (last N chars of output)
        assert "FAILED" in second_prompt or "AssertionError" in second_prompt

    async def test_usecase_complex_task_cost_limit(self):
        """Complex task fails repeatedly, hits cost limit, returns partial result."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=10)
        # Set cost limit to minimum allowed (1.0 USD)
        cost_config = ClaudeCodeCostConfig(max_cost_usd_per_loop=1.0)
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # Always returns fail with high token usage
        # Cost per call: (50000/1M)*15 + (50000/1M)*75 = 0.75 + 3.75 = 4.5 USD > 1.0
        fail_msg = _make_tool_message(
            output="Microservice partially built, tests failing...",
            exit_code=1,
            input_tokens=50_000,
            output_tokens=50_000,
        )
        handler = AsyncMock(return_value=fail_msg)

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Build microservice from spec"},
            "id": "tc1",
        }

        result = await mw.awrap_tool_call(request, handler)

        # Should abort quickly due to cost
        assert handler.call_count >= 1
        assert isinstance(result, ToolMessage)
        assert "cost limit exceeded" in result.content.lower()

    @patch("deep_agent.src.claude_code.loop_middleware._emit_progress")
    async def test_usecase_struggling_task(self, mock_emit):
        """Struggling task emits progress events after struggle_threshold."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(
            enabled=True, max_iterations=5, struggle_threshold=3
        )
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # Fails 4 times, then passes
        fail_msg = _make_tool_message(output="Test failed: error", exit_code=1)
        pass_msg = _make_tool_message(output="All tests passed!", exit_code=0)

        handler = AsyncMock(side_effect=[fail_msg, fail_msg, fail_msg, fail_msg, pass_msg])

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Fix bug"},
            "id": "tc1",
        }

        result = await mw.awrap_tool_call(request, handler)

        # Should succeed after 5 calls
        assert handler.call_count == 5
        assert "All tests passed!" in result.content

        # Check emit_progress was called with failed status for iterations >= struggle_threshold
        # Iterations 3, 4 should emit failed status
        failed_events = [
            call for call in mock_emit.call_args_list
            if call[0][0] == "loop_iteration"
            and call[0][1].get("status") == "failed"
        ]
        assert len(failed_events) >= 2  # At least iterations 3 and 4


class TestLoopMiddlewarePromptBuilding:
    """Test prompt construction with error context."""

    async def test_first_iteration_uses_original_prompt(self):
        """First iteration uses original prompt without error context."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=5)
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        pass_msg = _make_tool_message(output="Done", exit_code=0)
        handler = AsyncMock(return_value=pass_msg)

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Original prompt"},
            "id": "tc1",
        }

        await mw.awrap_tool_call(request, handler)

        # First call should have original prompt
        first_call = handler.call_args_list[0]
        first_request = first_call[0][0]
        assert first_request.tool_call["args"]["prompt"] == "Original prompt"

    async def test_retry_without_session_prepends_error_context(self):
        """Retry without session_id prepends error context to original prompt."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=5)
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # First call fails with no session_id
        fail_msg = _make_tool_message(
            output="Error: test_foo failed with AssertionError",
            exit_code=1,
            session_id="",
        )
        pass_msg = _make_tool_message(output="Done", exit_code=0)

        handler = AsyncMock(side_effect=[fail_msg, pass_msg])

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Original prompt"},
            "id": "tc1",
        }

        await mw.awrap_tool_call(request, handler)

        # Second call should have error context prepended
        second_call = handler.call_args_list[1]
        second_request = second_call[0][0]
        second_prompt = second_request.tool_call["args"]["prompt"]
        # Should start with error context
        assert "AssertionError" in second_prompt
        # Should contain original prompt
        assert "Original prompt" in second_prompt

    async def test_retry_with_session_uses_only_error_context(self):
        """Retry with session_id uses only error context (session has history)."""
        from deep_agent.src.claude_code.loop_middleware import (
            LoopEngineeringMiddleware,
        )

        config = LoopEngineeringConfig(enabled=True, max_iterations=5)
        cost_config = ClaudeCodeCostConfig()
        mw = LoopEngineeringMiddleware(config=config, cost_config=cost_config)

        # First call fails with session_id
        fail_msg = _make_tool_message(
            output="Error: test_foo failed with AssertionError",
            exit_code=1,
            session_id="session123",
        )
        pass_msg = _make_tool_message(output="Done", exit_code=0)

        handler = AsyncMock(side_effect=[fail_msg, pass_msg])

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {"prompt": "Original prompt"},
            "id": "tc1",
        }

        await mw.awrap_tool_call(request, handler)

        # Second call should have only error context (no original prompt)
        second_call = handler.call_args_list[1]
        second_request = second_call[0][0]
        second_prompt = second_request.tool_call["args"]["prompt"]
        # Should contain error context
        assert "AssertionError" in second_prompt
        # Should NOT contain original prompt (session has history)
        assert "Original prompt" not in second_prompt
