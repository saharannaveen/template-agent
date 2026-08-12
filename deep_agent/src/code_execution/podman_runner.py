"""Podman-based code execution runner for local development.

Runs code snippets in ephemeral Podman containers, mirroring the K8s runner
interface for seamless local/production parity.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from deep_agent.src.code_execution.config import CodeExecutionConfig

logger = logging.getLogger(__name__)


@dataclass
class PodmanExecutionResult:
    """Result of a Podman container code execution."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


class PodmanCodeRunner:
    """Run code snippets in ephemeral Podman containers."""

    def __init__(self, config: CodeExecutionConfig) -> None:
        """Initialize the runner with execution configuration."""
        self._config = config

    async def execute(
        self,
        language: str,
        code: str,
        timeout: int | None = None,
    ) -> PodmanExecutionResult:
        """Run a code snippet in an ephemeral Podman container."""
        image = self._config.images.get(language)
        entrypoint = self._config.entrypoints.get(language)

        if not image or not entrypoint:
            return PodmanExecutionResult(
                stdout="",
                stderr=f"Unsupported language: {language}. Supported: {', '.join(self._config.supported_languages)}",
                exit_code=1,
            )

        timeout = min(
            timeout or self._config.max_timeout_seconds,
            self._config.max_timeout_seconds,
        )

        import os

        podman_cmd = "podman"
        env = dict(os.environ)
        socket_path = "/var/run/podman.sock"
        if os.path.exists(socket_path):
            env["CONTAINER_HOST"] = f"unix://{socket_path}"
            podman_cmd = "podman"

        cmd = [
            podman_cmd,
            "run",
            "--rm",
            "--network",
            "none",
            "--memory",
            self._config.resource_limits.get("memory", "256Mi").replace("Mi", "m"),
            "--cpus",
            "0.5",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,size=64m",
            image,
            *entrypoint,
            code,
        ]

        logger.info("Executing %s code via Podman (timeout=%ds)", language, timeout)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return PodmanExecutionResult(
                    stdout="",
                    stderr=f"Execution timed out after {timeout}s",
                    exit_code=-1,
                    timed_out=True,
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")[
                : self._config.max_output_bytes
            ]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[
                : self._config.max_output_bytes
            ]

            return PodmanExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or 0,
            )

        except FileNotFoundError:
            return PodmanExecutionResult(
                stdout="",
                stderr="Code execution unavailable in this environment. Use claude_code tool for coding tasks instead, or deploy to OpenShift where K8s execution is available.",
                exit_code=1,
            )
        except Exception as exc:
            logger.error("Podman execution failed: %s", exc)
            return PodmanExecutionResult(
                stdout="",
                stderr=f"Execution error: {exc}",
                exit_code=1,
            )
