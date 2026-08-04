"""Unit tests for K8sSandbox backend adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deep_agent.src.code_execution.config import CodeExecutionConfig
from deep_agent.src.code_execution.k8s_sandbox import K8sSandbox


class TestK8sSandbox:
    """Test K8sSandbox implements SandboxBackendProtocol correctly."""

    def test_implements_sandbox_protocol(self):
        from deepagents.backends.protocol import SandboxBackendProtocol

        assert issubclass(K8sSandbox, SandboxBackendProtocol)

    def test_id_is_unique(self):
        s1 = K8sSandbox()
        s2 = K8sSandbox()
        assert s1.id != s2.id
        assert s1.id.startswith("k8s-sandbox-")

    def test_default_config(self):
        sandbox = K8sSandbox()
        assert sandbox._config.enabled is True
        assert sandbox._config.max_timeout_seconds == 60

    def test_custom_config(self):
        config = CodeExecutionConfig(enabled=True, max_timeout_seconds=120)
        sandbox = K8sSandbox(config=config)
        assert sandbox._config.max_timeout_seconds == 120

    @pytest.mark.asyncio
    async def test_aexecute_calls_runner(self):
        config = CodeExecutionConfig(enabled=True)
        sandbox = K8sSandbox(config=config)

        mock_result = MagicMock()
        mock_result.stdout = "hello world"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        sandbox._runner.run = AsyncMock(return_value=mock_result)
        sandbox._runner.resolve_namespace = MagicMock(return_value="test-ns")

        response = await sandbox.aexecute("echo hello")
        assert response.output == "hello world"
        assert response.exit_code == 0
        assert response.truncated is False

    @pytest.mark.asyncio
    async def test_aexecute_combines_stderr(self):
        config = CodeExecutionConfig(enabled=True)
        sandbox = K8sSandbox(config=config)

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = "warning"
        mock_result.exit_code = 0

        sandbox._runner.run = AsyncMock(return_value=mock_result)
        sandbox._runner.resolve_namespace = MagicMock(return_value="test-ns")

        response = await sandbox.aexecute("some command")
        assert "output" in response.output
        assert "warning" in response.output

    @pytest.mark.asyncio
    async def test_aexecute_respects_timeout(self):
        config = CodeExecutionConfig(enabled=True, max_timeout_seconds=30)
        sandbox = K8sSandbox(config=config)

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.exit_code = 0

        sandbox._runner.run = AsyncMock(return_value=mock_result)
        sandbox._runner.resolve_namespace = MagicMock(return_value="test-ns")

        await sandbox.aexecute("cmd", timeout=120)
        call_kwargs = sandbox._runner.run.call_args[1]
        assert call_kwargs["timeout"] == 30  # capped to max

    @pytest.mark.asyncio
    async def test_aexecute_truncates_output(self):
        config = CodeExecutionConfig(enabled=True, max_output_bytes=10)
        sandbox = K8sSandbox(config=config)

        mock_result = MagicMock()
        mock_result.stdout = "x" * 100
        mock_result.stderr = ""
        mock_result.exit_code = 0

        sandbox._runner.run = AsyncMock(return_value=mock_result)
        sandbox._runner.resolve_namespace = MagicMock(return_value="test-ns")

        response = await sandbox.aexecute("cmd")
        assert len(response.output) == 10
        assert response.truncated is True

    def test_upload_files_returns_errors(self):
        sandbox = K8sSandbox()
        responses = sandbox.upload_files([("/test.py", b"print('hi')")])
        assert len(responses) == 1
        assert "not supported" in responses[0].error.lower()

    def test_download_files_returns_errors(self):
        sandbox = K8sSandbox()
        responses = sandbox.download_files(["/test.py"])
        assert len(responses) == 1
        assert "not supported" in responses[0].error.lower()


class TestK8sSandboxBackendWiring:
    """Test that the backend builder recognizes k8s_sandbox type."""

    def test_build_k8s_sandbox_returns_instance(self):
        from deep_agent.src.infrastructure.backend import _build_k8s_sandbox

        mock_agent_config = MagicMock()
        mock_resolved = MagicMock()
        mock_resolved.code_execution = CodeExecutionConfig(enabled=True)
        mock_agent_config.resolve_agent_middleware.return_value = mock_resolved

        with patch(
            "deep_agent.src.agent.config.agent_config",
            mock_agent_config,
        ):
            result = _build_k8s_sandbox()
            assert isinstance(result, K8sSandbox)
