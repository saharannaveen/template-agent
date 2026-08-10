"""Tests for ClaudeCodeExecutionMiddleware."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deep_agent.src.claude_code.config import ClaudeCodeConfig


class TestClaudeCodeMiddlewareInit:
    def test_creates_runner_and_semaphores(self):
        """Test middleware initialization creates runner and semaphore dict."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware

        config = ClaudeCodeConfig(enabled=True)
        mw = ClaudeCodeExecutionMiddleware(config=config)

        # Runner created
        assert mw._runner is not None
        # Semaphore dict created
        assert isinstance(mw._semaphores, dict)
        assert len(mw._semaphores) == 0

    def test_get_semaphore_creates_per_org(self):
        """Test _get_semaphore creates one semaphore per org."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware

        config = ClaudeCodeConfig(enabled=True, max_concurrent_per_org=5)
        mw = ClaudeCodeExecutionMiddleware(config=config)

        sem_a = mw._get_semaphore("org-a")
        assert "org-a" in mw._semaphores
        assert sem_a._value == 5

        sem_b = mw._get_semaphore("org-b")
        assert "org-b" in mw._semaphores
        assert sem_b._value == 5

        # Same org returns same semaphore
        sem_a2 = mw._get_semaphore("org-a")
        assert sem_a is sem_a2


class TestClaudeCodeMiddlewareToolInjection:
    def test_wrap_model_call_passthrough(self):
        """Test wrap_model_call is synchronous pass-through."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware

        config = ClaudeCodeConfig(enabled=True)
        mw = ClaudeCodeExecutionMiddleware(config=config)

        request = MagicMock()
        handler = MagicMock(return_value=MagicMock())

        mw.wrap_model_call(request, handler)
        handler.assert_called_once_with(request)

    async def test_awrap_model_call_injects_tool_when_enabled(self):
        """Test awrap_model_call injects claude_code tool when enabled."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware

        config = ClaudeCodeConfig(enabled=True)
        mw = ClaudeCodeExecutionMiddleware(config=config)

        request = MagicMock()
        request.tools = [MagicMock()]

        override_request = MagicMock()
        request.override = MagicMock(return_value=override_request)
        handler = AsyncMock(return_value=MagicMock())

        await mw.awrap_model_call(request, handler)

        # Verify override was called with extended tools list
        request.override.assert_called_once()
        call_args = request.override.call_args
        assert "tools" in call_args.kwargs
        # Original tools should be included
        tools_list = call_args.kwargs["tools"]
        assert len(tools_list) > 1  # Original + claude_code tool

        # Handler called with overridden request
        handler.assert_called_once_with(override_request)

    async def test_awrap_model_call_passthrough_when_disabled(self):
        """Test awrap_model_call passes through when disabled."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware

        config = ClaudeCodeConfig(enabled=False)
        mw = ClaudeCodeExecutionMiddleware(config=config)

        request = MagicMock()
        handler = AsyncMock(return_value=MagicMock())

        await mw.awrap_model_call(request, handler)

        # No override, direct passthrough
        request.override.assert_not_called()
        handler.assert_called_once_with(request)


class TestClaudeCodeMiddlewareToolCallRouting:
    def test_wrap_tool_call_passthrough(self):
        """Test wrap_tool_call is synchronous pass-through."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware

        config = ClaudeCodeConfig(enabled=True)
        mw = ClaudeCodeExecutionMiddleware(config=config)

        request = MagicMock()
        handler = MagicMock(return_value=MagicMock())

        mw.wrap_tool_call(request, handler)
        handler.assert_called_once_with(request)

    async def test_awrap_tool_call_passthrough_non_claude_code(self):
        """Test awrap_tool_call passes through non-claude_code tools."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware

        config = ClaudeCodeConfig(enabled=True)
        mw = ClaudeCodeExecutionMiddleware(config=config)

        request = MagicMock()
        request.tool_call = {"name": "search_web", "args": {}, "id": "tc1"}
        handler = AsyncMock(return_value=MagicMock())

        await mw.awrap_tool_call(request, handler)
        handler.assert_called_once_with(request)

    @patch("os.environ.get")
    async def test_awrap_tool_call_intercepts_claude_code(self, mock_env_get):
        """Test awrap_tool_call intercepts claude_code tool and routes to runner."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        # Mock environment
        def env_side_effect(key, default=None):
            if key == "AI_PLATFORM_AGENT_ORG":
                return "test-org"
            return default

        mock_env_get.side_effect = env_side_effect

        # Create middleware with mocked runner
        config = ClaudeCodeConfig(enabled=True)
        mw = ClaudeCodeExecutionMiddleware(config=config)

        # Mock the runner's execute method
        mock_result = ClaudeCodeResult(
            output="Task completed successfully",
            session_id="session123",
            exit_code=0,
            is_error=False,
            duration_seconds=2.5,
            raw_json={"foo": "bar"},
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=100,
            cache_creation_tokens=50,
            model="claude-opus-4-6",
        )
        mw._runner.execute = AsyncMock(return_value=mock_result)

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {
                "prompt": "Write hello world",
                "task_name": "hello-task",
                "task_type": "implementation",
                "workspace": "/workspace",
                "allowed_tools": ["Read", "Write"],
                "session_id": None,
            },
            "id": "tc1",
        }
        handler = AsyncMock()

        result = await mw.awrap_tool_call(request, handler)

        # Handler should NOT be called
        handler.assert_not_called()

        # Runner execute should be called
        mw._runner.execute.assert_called_once()
        call_kwargs = mw._runner.execute.call_args.kwargs
        assert call_kwargs["prompt"] == "Write hello world"
        # When workspace is "/workspace", a temp directory should be created in ~/.claude-workspaces
        workspace_path = call_kwargs["workspace_path"]
        import os
        assert workspace_path.startswith(os.path.expanduser("~/.claude-workspaces/task-"))
        assert call_kwargs["allowed_tools"] == ["Read", "Write"]
        assert call_kwargs["session_id"] is None
        assert call_kwargs["task_type"] == "implementation"

        # Result should be ToolMessage
        from langchain_core.messages import ToolMessage

        assert isinstance(result, ToolMessage)
        assert result.tool_call_id == "tc1"
        # Output should include usage summary
        assert "Task completed successfully" in result.content
        assert "📊 **Usage:**" in result.content
        assert "claude-opus-4-6" in result.content
        assert "1000/500" in result.content  # tokens in/out
        assert "duration=" in result.content  # duration field exists
        assert "s" in result.content  # seconds unit
        # Cost should be in there too
        assert "$" in result.content

        # additional_kwargs should contain the full result
        assert "claude_code_result" in result.additional_kwargs
        result_dict = result.additional_kwargs["claude_code_result"]
        assert result_dict["session_id"] == "session123"
        assert result_dict["model"] == "claude-opus-4-6"

    @patch("os.environ.get")
    async def test_awrap_tool_call_queue_timeout(self, mock_env_get):
        """Test awrap_tool_call rejects with ToolMessage when queue timeout."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware

        # Mock environment
        def env_side_effect(key, default=None):
            if key == "AI_PLATFORM_AGENT_ORG":
                return "test-org"
            return default

        mock_env_get.side_effect = env_side_effect

        # Create middleware with low queue timeout and max_concurrent=1
        config = ClaudeCodeConfig(
            enabled=True,
            max_concurrent_per_org=1,
            queue_timeout_seconds=1.0,  # Minimum allowed value
        )
        mw = ClaudeCodeExecutionMiddleware(config=config)

        # Acquire the semaphore to simulate queue full
        sem = mw._get_semaphore("test-org")
        await sem.acquire()

        try:
            request = MagicMock()
            request.tool_call = {
                "name": "claude_code",
                "args": {
                    "prompt": "Test prompt",
                    "task_name": "test-task",
                },
                "id": "tc1",
            }
            handler = AsyncMock()

            result = await mw.awrap_tool_call(request, handler)

            # Should get rejection ToolMessage
            from langchain_core.messages import ToolMessage

            assert isinstance(result, ToolMessage)
            assert result.tool_call_id == "tc1"
            assert "queue full" in result.content.lower() or "try again" in result.content.lower()

            # Handler should NOT be called
            handler.assert_not_called()
        finally:
            sem.release()

    @patch("os.environ.get")
    async def test_awrap_tool_call_resolves_model_from_task_type(self, mock_env_get):
        """Test awrap_tool_call resolves model based on task_type."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        # Mock environment
        def env_side_effect(key, default=None):
            if key == "AI_PLATFORM_AGENT_ORG":
                return "test-org"
            return default

        mock_env_get.side_effect = env_side_effect

        # Create middleware
        config = ClaudeCodeConfig(enabled=True)
        mw = ClaudeCodeExecutionMiddleware(config=config)

        # Mock the runner's execute method
        mock_result = ClaudeCodeResult(
            output="Tests written",
            session_id="session456",
            exit_code=0,
            is_error=False,
            duration_seconds=1.5,
            raw_json={},
            input_tokens=500,
            output_tokens=300,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="claude-sonnet-4-5",  # test_writing uses sonnet
        )
        mw._runner.execute = AsyncMock(return_value=mock_result)

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {
                "prompt": "Write tests",
                "task_name": "test-task",
                "task_type": "test_writing",  # Should route to sonnet
                "workspace": "/workspace",
            },
            "id": "tc2",
        }
        handler = AsyncMock()

        result = await mw.awrap_tool_call(request, handler)

        # Verify the task_type was passed to execute
        mw._runner.execute.assert_called_once()
        call_kwargs = mw._runner.execute.call_args.kwargs
        assert call_kwargs["task_type"] == "test_writing"

        # Result should contain the model name
        assert "claude-sonnet-4-5" in result.content

    @patch("os.environ.get")
    async def test_awrap_tool_call_computes_cost(self, mock_env_get):
        """Test awrap_tool_call computes and includes cost in response."""
        from deep_agent.src.claude_code.middleware import ClaudeCodeExecutionMiddleware
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        # Mock environment
        def env_side_effect(key, default=None):
            if key == "AI_PLATFORM_AGENT_ORG":
                return "test-org"
            return default

        mock_env_get.side_effect = env_side_effect

        # Create middleware with specific pricing
        config = ClaudeCodeConfig(enabled=True)
        config.cost.pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        mw = ClaudeCodeExecutionMiddleware(config=config)

        # Mock result with 1M input, 0.5M output tokens
        mock_result = ClaudeCodeResult(
            output="Done",
            session_id="session789",
            exit_code=0,
            is_error=False,
            duration_seconds=3.0,
            raw_json={},
            input_tokens=1_000_000,
            output_tokens=500_000,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="claude-opus-4-6",
        )
        mw._runner.execute = AsyncMock(return_value=mock_result)

        request = MagicMock()
        request.tool_call = {
            "name": "claude_code",
            "args": {
                "prompt": "Big task",
                "task_name": "big-task",
            },
            "id": "tc3",
        }
        handler = AsyncMock()

        result = await mw.awrap_tool_call(request, handler)

        # Cost should be: (1M / 1M) * 15 + (0.5M / 1M) * 75 = 15 + 37.5 = 52.5
        assert "$52.5" in result.content or "$52.50" in result.content
