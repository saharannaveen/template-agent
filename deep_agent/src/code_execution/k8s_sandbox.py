"""K8s sandbox backend implementing deepagents SandboxBackendProtocol.

Wraps K8sJobRunner to provide sandboxed code execution via ephemeral K8s Jobs.
Plugs into deepagents' FilesystemMiddleware so the agent gets an `execute` tool
automatically — no custom middleware needed.
"""

from __future__ import annotations

import asyncio
import uuid

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

from deep_agent.src.code_execution.config import CodeExecutionConfig
from deep_agent.src.code_execution.k8s_job_runner import K8sJobRunner


class K8sSandbox(BaseSandbox):
    """Sandbox backend that runs commands in ephemeral K8s Jobs.

    Each execute() call creates a K8s Job, runs the command in a container
    with full security hardening (read-only rootfs, dropped capabilities,
    seccomp, NetworkPolicy), collects output, and cleans up.
    """

    def __init__(self, config: CodeExecutionConfig | None = None) -> None:
        """Initialize the K8s sandbox with optional configuration."""
        self._config = config or CodeExecutionConfig(enabled=True)
        self._runner = K8sJobRunner(self._config)
        self._id = f"k8s-sandbox-{uuid.uuid4().hex[:8]}"

    @property
    def id(self) -> str:
        """Return the unique sandbox instance identifier."""
        return self._id

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a command synchronously in an ephemeral K8s Job."""
        effective_timeout = min(
            timeout or self._config.max_timeout_seconds,
            self._config.max_timeout_seconds,
        )
        result = asyncio.get_event_loop().run_until_complete(
            self._runner.run(
                language="shell",
                code=command,
                timeout=effective_timeout,
                namespace=self._runner.resolve_namespace(),
            )
        )
        output = result.stdout
        if result.stderr:
            output = f"{output}\n{result.stderr}" if output else result.stderr

        truncated = len(output) > self._config.max_output_bytes
        if truncated:
            output = output[: self._config.max_output_bytes]

        return ExecuteResponse(
            output=output,
            exit_code=result.exit_code,
            truncated=truncated,
        )

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a command asynchronously in an ephemeral K8s Job."""
        effective_timeout = min(
            timeout or self._config.max_timeout_seconds,
            self._config.max_timeout_seconds,
        )
        result = await self._runner.run(
            language="shell",
            code=command,
            timeout=effective_timeout,
            namespace=self._runner.resolve_namespace(),
        )
        output = result.stdout
        if result.stderr:
            output = f"{output}\n{result.stderr}" if output else result.stderr

        truncated = len(output) > self._config.max_output_bytes
        if truncated:
            output = output[: self._config.max_output_bytes]

        return ExecuteResponse(
            output=output,
            exit_code=result.exit_code,
            truncated=truncated,
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload files (not supported in ephemeral K8s Jobs)."""
        responses = []
        for path, content in files:
            responses.append(
                FileUploadResponse(
                    path=path,
                    error=f"Upload not supported in ephemeral K8s Jobs (path: {path})",
                )
            )
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files (not supported in ephemeral K8s Jobs)."""
        responses = []
        for path in paths:
            responses.append(
                FileDownloadResponse(
                    path=path,
                    error=f"Download not supported in ephemeral K8s Jobs (path: {path})",
                )
            )
        return responses
