"""Tests for Claude Code runner implementations."""

from __future__ import annotations

import json

import pytest


class TestTestResult:
    def test_create_test_result(self):
        from deep_agent.src.claude_code.runner import TestResult

        result = TestResult(passed=True, signal="exit_code", details="Exit code 0")
        assert result.passed is True
        assert result.signal == "exit_code"
        assert result.details == "Exit code 0"


class TestClaudeCodeResult:
    def test_create_result(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        result = ClaudeCodeResult(
            output="test output",
            session_id="abc123",
            exit_code=0,
            is_error=False,
            duration_seconds=1.5,
            raw_json={"foo": "bar"},
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=10,
            cache_creation_tokens=5,
            model="claude-opus-4-6",
        )
        assert result.output == "test output"
        assert result.session_id == "abc123"
        assert result.exit_code == 0
        assert result.is_error is False
        assert result.duration_seconds == 1.5
        assert result.raw_json == {"foo": "bar"}
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cache_read_tokens == 10
        assert result.cache_creation_tokens == 5
        assert result.model == "claude-opus-4-6"

    def test_test_result_passes_on_clean_exit(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        result = ClaudeCodeResult(
            output="All tests passed",
            session_id="abc123",
            exit_code=0,
            is_error=False,
            duration_seconds=1.5,
            raw_json={},
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="claude-opus-4-6",
        )
        test_result = result.test_result
        assert test_result.passed is True
        assert test_result.signal == "output_pattern"

    def test_test_result_fails_on_is_error(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        result = ClaudeCodeResult(
            output="output",
            session_id="abc123",
            exit_code=0,
            is_error=True,
            duration_seconds=1.5,
            raw_json={},
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="claude-opus-4-6",
        )
        test_result = result.test_result
        assert test_result.passed is False
        assert test_result.signal == "json_field"

    def test_test_result_fails_on_nonzero_exit(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        result = ClaudeCodeResult(
            output="output",
            session_id="abc123",
            exit_code=1,
            is_error=False,
            duration_seconds=1.5,
            raw_json={},
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="claude-opus-4-6",
        )
        test_result = result.test_result
        assert test_result.passed is False
        assert test_result.signal == "exit_code"

    def test_test_result_fails_on_failure_markers(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        failure_outputs = [
            "Test failed",
            "Failure in test",
            "Error: something went wrong",
            "Traceback (most recent call last):",
            "AssertionError: expected != actual",
        ]
        for output in failure_outputs:
            result = ClaudeCodeResult(
                output=output,
                session_id="abc123",
                exit_code=0,
                is_error=False,
                duration_seconds=1.5,
                raw_json={},
                input_tokens=100,
                output_tokens=50,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                model="claude-opus-4-6",
            )
            test_result = result.test_result
            assert test_result.passed is False, f"Should fail on: {output}"
            assert test_result.signal == "output_pattern"

    def test_test_result_passes_when_only_pass_markers(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        pass_outputs = [
            "All tests passed",
            "Tests pass successfully",
            "5 tests ok",
        ]
        for output in pass_outputs:
            result = ClaudeCodeResult(
                output=output,
                session_id="abc123",
                exit_code=0,
                is_error=False,
                duration_seconds=1.5,
                raw_json={},
                input_tokens=100,
                output_tokens=50,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                model="claude-opus-4-6",
            )
            test_result = result.test_result
            assert test_result.passed is True, f"Should pass on: {output}"
            assert test_result.signal == "output_pattern"

    def test_test_result_passes_when_no_markers(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        result = ClaudeCodeResult(
            output="Some normal output without markers",
            session_id="abc123",
            exit_code=0,
            is_error=False,
            duration_seconds=1.5,
            raw_json={},
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="claude-opus-4-6",
        )
        test_result = result.test_result
        assert test_result.passed is True
        assert test_result.signal == "output_pattern"

    def test_compute_cost_calculates_correctly(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        result = ClaudeCodeResult(
            output="output",
            session_id="abc123",
            exit_code=0,
            is_error=False,
            duration_seconds=1.5,
            raw_json={},
            input_tokens=1_000_000,  # 1M tokens
            output_tokens=500_000,  # 0.5M tokens
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="claude-opus-4-6",
        )
        pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,  # $15 per million tokens
                "output_per_mtok": 75.0,  # $75 per million tokens
            }
        }
        cost = result.compute_cost(pricing)
        # (1_000_000 / 1_000_000) * 15.0 + (500_000 / 1_000_000) * 75.0
        # = 1 * 15.0 + 0.5 * 75.0 = 15.0 + 37.5 = 52.5
        assert cost == 52.5

    def test_compute_cost_returns_zero_for_unknown_model(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        result = ClaudeCodeResult(
            output="output",
            session_id="abc123",
            exit_code=0,
            is_error=False,
            duration_seconds=1.5,
            raw_json={},
            input_tokens=1_000_000,
            output_tokens=500_000,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="unknown-model",
        )
        pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        cost = result.compute_cost(pricing)
        assert cost == 0.0

    def test_format_includes_output(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        result = ClaudeCodeResult(
            output="test output content",
            session_id="abc123",
            exit_code=0,
            is_error=False,
            duration_seconds=1.5,
            raw_json={},
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="claude-opus-4-6",
        )
        formatted = result.format()
        assert "test output content" in formatted

    def test_format_appends_exit_code_if_nonzero(self):
        from deep_agent.src.claude_code.runner import ClaudeCodeResult

        result = ClaudeCodeResult(
            output="test output",
            session_id="abc123",
            exit_code=1,
            is_error=False,
            duration_seconds=1.5,
            raw_json={},
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            model="claude-opus-4-6",
        )
        formatted = result.format()
        assert "test output" in formatted
        assert "1" in formatted


class TestPodmanClaudeCodeRunnerBuildCommand:
    def test_build_base_args_minimal(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

        config = ClaudeCodeConfig(max_turns=50)
        runner = PodmanClaudeCodeRunner(config)
        args = runner._build_base_args("test prompt")

        assert "-p" in args
        assert "--output-format" in args
        assert "json" in args
        assert "--bare" in args
        assert "--dangerously-skip-permissions" in args
        assert "--max-turns" in args
        assert "50" in args
        assert "test prompt" == args[-1]

    def test_build_base_args_with_allowed_tools(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

        config = ClaudeCodeConfig(max_turns=50)
        runner = PodmanClaudeCodeRunner(config)
        args = runner._build_base_args("test prompt", allowed_tools=["Read", "Write", "Bash"])

        assert "--allowedTools" in args
        allowed_tools_idx = args.index("--allowedTools")
        assert args[allowed_tools_idx + 1] == "Read,Write,Bash"

    def test_build_base_args_with_session(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

        config = ClaudeCodeConfig(max_turns=50)
        runner = PodmanClaudeCodeRunner(config)
        args = runner._build_base_args("test prompt", session_id="session123")

        assert "--resume" in args
        resume_idx = args.index("--resume")
        assert args[resume_idx + 1] == "session123"

    def test_build_base_args_with_model(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

        config = ClaudeCodeConfig(max_turns=50)
        runner = PodmanClaudeCodeRunner(config)
        args = runner._build_base_args("test prompt", model="claude-sonnet-4-5")

        assert "--model" in args
        model_idx = args.index("--model")
        assert args[model_idx + 1] == "claude-sonnet-4-5"

    def test_build_env_args_vertex(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

        config = ClaudeCodeConfig.model_validate({
            "auth": {
                "type": "vertex",
                "vertex_project_id": "my-project-123",
            }
        })
        runner = PodmanClaudeCodeRunner(config)
        env_args = runner._build_env_args()

        assert "-e" in env_args
        assert "CLAUDE_CODE_USE_VERTEX=1" in env_args
        assert "ANTHROPIC_VERTEX_PROJECT_ID=my-project-123" in env_args

    def test_build_env_args_api_key(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner
        import os

        # Set env var for test
        os.environ["ANTHROPIC_API_KEY"] = "test-key-123"
        try:
            config = ClaudeCodeConfig.model_validate({
                "auth": {
                    "type": "api_key",
                }
            })
            runner = PodmanClaudeCodeRunner(config)
            env_args = runner._build_env_args()

            assert "-e" in env_args
            assert "ANTHROPIC_API_KEY=test-key-123" in env_args
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_build_env_args_oauth(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner
        import os

        # Set env var for test
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "oauth-token-123"
        try:
            config = ClaudeCodeConfig.model_validate({
                "auth": {
                    "type": "oauth",
                }
            })
            runner = PodmanClaudeCodeRunner(config)
            env_args = runner._build_env_args()

            assert "-e" in env_args
            assert "CLAUDE_CODE_OAUTH_TOKEN=oauth-token-123" in env_args
        finally:
            del os.environ["CLAUDE_CODE_OAUTH_TOKEN"]

    def test_build_command_includes_podman_run(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

        config = ClaudeCodeConfig(image="claude-sandbox:test")
        runner = PodmanClaudeCodeRunner(config)
        cmd = runner._build_command("test prompt", "/workspace/path")

        assert cmd[0] == "podman"
        assert "run" in cmd
        assert "--rm" in cmd
        assert "claude-sandbox:test" in cmd

    def test_build_command_includes_workspace_mount(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

        config = ClaudeCodeConfig()
        runner = PodmanClaudeCodeRunner(config)
        cmd = runner._build_command("test prompt", "/workspace/path")

        # Find -v flag
        v_indices = [i for i, x in enumerate(cmd) if x == "-v"]
        assert len(v_indices) > 0
        # Check if workspace mount exists
        workspace_mounted = any(
            "/workspace/path:/workspace" in cmd[i + 1]
            for i in v_indices
        )
        assert workspace_mounted

    def test_parse_result_success(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

        config = ClaudeCodeConfig()
        runner = PodmanClaudeCodeRunner(config)

        json_output = {
            "session_id": "session123",
            "result": "test output",
            "is_error": False,
            "modelUsage": {
                "claude-opus-4-6": {
                    "inputTokens": 1000,
                    "outputTokens": 500,
                    "cacheReadTokens": 100,
                    "cacheCreationTokens": 50,
                }
            }
        }
        stdout = json.dumps(json_output).encode()
        stderr = b""

        result = runner._parse_result(stdout, stderr, 0, 1.5)

        assert result.session_id == "session123"
        assert result.output == "test output"
        assert result.exit_code == 0
        assert result.is_error is False
        assert result.duration_seconds == 1.5
        assert result.input_tokens == 1000
        assert result.output_tokens == 500
        assert result.cache_read_tokens == 100
        assert result.cache_creation_tokens == 50
        assert result.model == "claude-opus-4-6"

    def test_parse_result_error_on_bad_json(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

        config = ClaudeCodeConfig()
        runner = PodmanClaudeCodeRunner(config)

        stdout = b"not valid json"
        stderr = b"some error"

        result = runner._parse_result(stdout, stderr, 1, 1.5)

        assert result.is_error is True
        assert result.exit_code == 1
        assert "not valid json" in result.output or "some error" in result.output


class TestPodmanClaudeCodeRunnerSessionMethods:
    @pytest.mark.asyncio
    async def test_create_session_returns_container_name(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner
        from unittest.mock import AsyncMock, MagicMock

        config = ClaudeCodeConfig(image="claude-sandbox:test")
        runner = PodmanClaudeCodeRunner(config)

        # Mock the subprocess call
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"container-id-12345\n", b""))

        import asyncio
        original_create = asyncio.create_subprocess_exec

        async def mock_create_subprocess(*args, **kwargs):
            return mock_proc

        asyncio.create_subprocess_exec = mock_create_subprocess

        try:
            container_name = await runner.create_session("session-abc", "/workspace/test")
            assert container_name == "claude-session-session-abc"
        finally:
            asyncio.create_subprocess_exec = original_create

    @pytest.mark.asyncio
    async def test_execute_in_session_calls_podman_exec(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner
        from unittest.mock import AsyncMock, MagicMock
        import json

        config = ClaudeCodeConfig(image="claude-sandbox:test", timeout_seconds=60)
        runner = PodmanClaudeCodeRunner(config)

        # Mock successful JSON response
        json_output = {
            "session_id": "session123",
            "result": "test output",
            "is_error": False,
            "modelUsage": {
                "claude-opus-4-6": {
                    "inputTokens": 100,
                    "outputTokens": 50,
                    "cacheReadTokens": 0,
                    "cacheCreationTokens": 0,
                }
            }
        }

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(json.dumps(json_output).encode(), b""))
        mock_proc.returncode = 0

        import asyncio
        original_create = asyncio.create_subprocess_exec

        async def mock_create_subprocess(*args, **kwargs):
            # Verify podman exec is called
            assert args[0] == "podman"
            assert args[1] == "exec"
            assert args[2] == "claude-session-test"
            assert args[3] == "claude"
            return mock_proc

        asyncio.create_subprocess_exec = mock_create_subprocess

        try:
            result = await runner.execute_in_session("claude-session-test", "test prompt")
            assert result.output == "test output"
            assert result.exit_code == 0
            assert result.is_error is False
        finally:
            asyncio.create_subprocess_exec = original_create

    @pytest.mark.asyncio
    async def test_execute_in_session_timeout_does_not_kill_container(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner
        from unittest.mock import AsyncMock, MagicMock, PropertyMock

        config = ClaudeCodeConfig(image="claude-sandbox:test", timeout_seconds=30)
        runner = PodmanClaudeCodeRunner(config)

        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()
        # Set returncode properly
        type(mock_proc).returncode = PropertyMock(return_value=None)

        # Simulate timeout
        async def mock_communicate():
            import asyncio
            await asyncio.sleep(40)  # Will timeout before this completes
            return (b"", b"")

        mock_proc.communicate = mock_communicate

        import asyncio
        original_create = asyncio.create_subprocess_exec

        async def mock_create_subprocess(*args, **kwargs):
            return mock_proc

        asyncio.create_subprocess_exec = mock_create_subprocess

        try:
            result = await runner.execute_in_session("claude-session-test", "test prompt")
            # Verify timeout result
            assert result.exit_code == 124
            assert result.is_error is True
            assert "timed out" in result.output.lower()
            # Verify process.kill was called (exec process killed, not container)
            mock_proc.kill.assert_called_once()
        finally:
            asyncio.create_subprocess_exec = original_create

    @pytest.mark.asyncio
    async def test_stop_session_calls_podman_stop(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner
        from unittest.mock import AsyncMock, MagicMock

        config = ClaudeCodeConfig(image="claude-sandbox:test")
        runner = PodmanClaudeCodeRunner(config)

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        import asyncio
        original_create = asyncio.create_subprocess_exec

        async def mock_create_subprocess(*args, **kwargs):
            assert args[0] == "podman"
            assert args[1] == "stop"
            assert args[2] == "claude-session-test"
            return mock_proc

        asyncio.create_subprocess_exec = mock_create_subprocess

        try:
            await runner.stop_session("claude-session-test")
        finally:
            asyncio.create_subprocess_exec = original_create

    @pytest.mark.asyncio
    async def test_start_session_calls_podman_start(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner
        from unittest.mock import AsyncMock, MagicMock

        config = ClaudeCodeConfig(image="claude-sandbox:test")
        runner = PodmanClaudeCodeRunner(config)

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        import asyncio
        original_create = asyncio.create_subprocess_exec

        async def mock_create_subprocess(*args, **kwargs):
            assert args[0] == "podman"
            assert args[1] == "start"
            assert args[2] == "claude-session-test"
            return mock_proc

        asyncio.create_subprocess_exec = mock_create_subprocess

        try:
            await runner.start_session("claude-session-test")
        finally:
            asyncio.create_subprocess_exec = original_create

    @pytest.mark.asyncio
    async def test_destroy_session_calls_podman_stop_and_rm(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner
        from unittest.mock import AsyncMock, MagicMock

        config = ClaudeCodeConfig(image="claude-sandbox:test")
        runner = PodmanClaudeCodeRunner(config)

        call_count = {"stop": 0, "rm": 0}

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        import asyncio
        original_create = asyncio.create_subprocess_exec

        async def mock_create_subprocess(*args, **kwargs):
            assert args[0] == "podman"
            if args[1] == "stop":
                call_count["stop"] += 1
                assert args[2] == "claude-session-test"
            elif args[1] == "rm":
                call_count["rm"] += 1
                assert args[2] == "claude-session-test"
            return mock_proc

        asyncio.create_subprocess_exec = mock_create_subprocess

        try:
            await runner.destroy_session("claude-session-test")
            # Verify both stop and rm were called
            assert call_count["stop"] == 1
            assert call_count["rm"] == 1
        finally:
            asyncio.create_subprocess_exec = original_create
