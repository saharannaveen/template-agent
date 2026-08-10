"""Claude Code runner implementations for executing Claude in containers."""

from __future__ import annotations

import asyncio
import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from deep_agent.src.claude_code.config import ClaudeCodeConfig


@dataclass
class TestResult:
    """Result of test execution detection."""

    passed: bool
    signal: str  # "json_field", "exit_code", "output_pattern"
    details: str


@dataclass
class ClaudeCodeResult:
    """Result from a Claude Code execution."""

    output: str
    session_id: str
    exit_code: int
    is_error: bool
    duration_seconds: float
    raw_json: dict
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    model: str

    @property
    def test_result(self) -> TestResult:
        """Detect test success/failure using three-signal detection."""
        # Signal 1: is_error field
        if self.is_error:
            return TestResult(
                passed=False,
                signal="json_field",
                details="is_error=True in result",
            )

        # Signal 2: exit_code
        if self.exit_code != 0:
            return TestResult(
                passed=False,
                signal="exit_code",
                details=f"Non-zero exit code: {self.exit_code}",
            )

        # Signal 3: output pattern analysis
        output_lower = self.output.lower()

        # Failure markers
        fail_markers = ["failed", "failure", "error", "traceback", "assert"]
        has_fail = any(marker in output_lower for marker in fail_markers)

        # Pass markers
        pass_markers = ["passed", "tests pass", "all tests", " ok"]
        has_pass = any(marker in output_lower for marker in pass_markers)

        if has_pass and not has_fail:
            return TestResult(
                passed=True,
                signal="output_pattern",
                details="Pass markers found without failure markers",
            )
        elif has_fail:
            return TestResult(
                passed=False,
                signal="output_pattern",
                details="Failure markers detected in output",
            )
        else:
            # Neither markers found - assume passed
            return TestResult(
                passed=True,
                signal="output_pattern",
                details="No failure markers detected",
            )

    def compute_cost(self, pricing: dict) -> float:
        """Compute cost from token counts using pricing config.

        Args:
            pricing: Dict of model -> {input_per_mtok, output_per_mtok}
                    Prices are per MILLION tokens.

        Returns:
            Cost in USD, or 0.0 if model not in pricing dict.
        """
        if self.model not in pricing:
            return 0.0

        model_pricing = pricing[self.model]
        input_cost = (self.input_tokens / 1_000_000) * model_pricing.get("input_per_mtok", 15.0)
        output_cost = (self.output_tokens / 1_000_000) * model_pricing.get("output_per_mtok", 75.0)

        return input_cost + output_cost

    def format(self) -> str:
        """Format result as human-readable output."""
        result = self.output
        if self.exit_code != 0:
            result += f"\n(exit code: {self.exit_code})"
        return result


class BaseClaudeCodeRunner(ABC):
    """Base class for Claude Code runners."""

    def __init__(self, config: ClaudeCodeConfig):
        """Initialize runner with config."""
        self.config = config

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        workspace_path: str,
        allowed_tools: list[str] | None = None,
        session_id: str | None = None,
        task_type: str | None = None,
    ) -> ClaudeCodeResult:
        """Execute Claude Code and return result."""
        pass

    def _build_base_args(
        self,
        prompt: str,
        allowed_tools: list[str] | None = None,
        session_id: str | None = None,
        model: str | None = None,
    ) -> list[str]:
        """Build base CLI arguments for Claude Code.

        Always includes: -p, --output-format json, --bare,
        --dangerously-skip-permissions, --max-turns
        Optional: --allowedTools, --resume, --model
        Last arg: prompt
        """
        args = [
            "-p",
            "--output-format",
            "json",
            "--bare",
            "--dangerously-skip-permissions",
            "--max-turns",
            str(self.config.max_turns),
        ]

        if allowed_tools:
            args.extend(["--allowedTools", ",".join(allowed_tools)])

        if session_id:
            args.extend(["--resume", session_id])

        if model:
            args.extend(["--model", model])

        args.append(prompt)

        return args


class PodmanClaudeCodeRunner(BaseClaudeCodeRunner):
    """Podman-based Claude Code runner."""

    def _build_env_args(self) -> list[str]:
        """Build environment variable and mount args based on auth type."""
        env_args = []

        if self.config.auth.type == "vertex":
            env_args.extend(["-e", "CLAUDE_CODE_USE_VERTEX=1"])
            # Fall back to environment variable if config value is empty
            project_id = self.config.auth.vertex_project_id or os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")
            env_args.extend([
                "-e",
                f"ANTHROPIC_VERTEX_PROJECT_ID={project_id}",
            ])

            # Mount GCP ADC if file exists
            gcp_adc_path = os.path.expanduser(
                "~/.config/gcloud/application_default_credentials.json"
            )
            if os.path.exists(gcp_adc_path):
                container_adc_path = "/gcp/application_default_credentials.json"
                env_args.extend(["-e", f"GOOGLE_APPLICATION_CREDENTIALS={container_adc_path}"])
                env_args.extend(["-v", f"{gcp_adc_path}:{container_adc_path}:ro"])

        elif self.config.auth.type == "api_key":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            env_args.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])

        elif self.config.auth.type == "oauth":
            oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
            env_args.extend(["-e", f"CLAUDE_CODE_OAUTH_TOKEN={oauth_token}"])

        # Pass through integration tokens if available
        github_token = os.environ.get("GITHUB_TOKEN", "")
        if github_token:
            env_args.extend(["-e", f"GITHUB_TOKEN={github_token}"])

        gitlab_token = os.environ.get("GITLAB_TOKEN", "")
        if gitlab_token:
            env_args.extend(["-e", f"GITLAB_TOKEN={gitlab_token}"])

        return env_args

    @staticmethod
    @staticmethod
    def _extract_repo_url(prompt: str) -> tuple[str, str]:
        """Extract GitHub/GitLab repo URL and branch from prompt."""
        import re
        url_match = re.search(r'https://(?:github\.com|gitlab\.com)/[\w\-\.]+/[\w\-\.]+(?:\.git)?', prompt)
        repo_url = url_match.group(0) if url_match else ""
        # Try multiple branch patterns
        branch = ""
        patterns = [
            r'(?:name\s+it|named?)\s+[`"]?(feat/[\w\-]+|fix/[\w\-]+|[\w\-]+/[\w\-]+)[`"]?',
            r'branch\s+[`"]?(feat/[\w\-]+|fix/[\w\-]+)[`"]?',
            r'checkout\s+-[bB]\s+[`"]?([\w\-/]+)[`"]?',
            r'branch\s+[`"]?([\w\-]+/[\w\-]+)[`"]?',
        ]
        for pat in patterns:
            m = re.search(pat, prompt, re.IGNORECASE)
            if m:
                branch = m.group(1)
                if branch not in ('from', 'to', 'the', 'a', 'in', 'on'):
                    break
                branch = ""
        return repo_url, branch

    def _build_command(
        self,
        prompt: str,
        workspace_path: str,
        allowed_tools: list[str] | None = None,
        session_id: str | None = None,
        model: str | None = None,
        repo_url: str | None = None,
        repo_branch: str | None = None,
    ) -> list[str]:
        """Build full podman command."""
        cmd = ["podman", "run", "--rm"]

        # Add environment args
        cmd.extend(self._build_env_args())

        # Pass repo URL so entrypoint clones it before Claude Code runs
        if not repo_url:
            repo_url, repo_branch_extracted = self._extract_repo_url(prompt)
            if not repo_branch:
                repo_branch = repo_branch_extracted
        if repo_url:
            cmd.extend(["-e", f"REPO_URL={repo_url}"])
            if repo_branch:
                cmd.extend(["-e", f"REPO_BRANCH={repo_branch}"])

        # Add workspace mount
        cmd.extend(["-v", f"{workspace_path}:/workspace"])

        # Add image
        cmd.append(self.config.image)

        # Add base args
        cmd.extend(self._build_base_args(prompt, allowed_tools, session_id, model))

        return cmd

    def _parse_result(
        self,
        stdout: bytes,
        stderr: bytes,
        returncode: int,
        duration: float,
    ) -> ClaudeCodeResult:
        """Parse Claude Code JSON output into ClaudeCodeResult."""
        try:
            raw = stdout.decode()
            json_start = raw.find("{")
            if json_start > 0:
                raw = raw[json_start:]
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # JSON parse failed - return error result
            error_output = stdout.decode(errors="replace")
            if stderr:
                error_output += "\n" + stderr.decode(errors="replace")

            return ClaudeCodeResult(
                output=error_output,
                session_id="",
                exit_code=returncode,
                is_error=True,
                duration_seconds=duration,
                raw_json={},
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                model="",
            )

        # Extract token counts from first model in modelUsage
        model_usage = data.get("modelUsage", {})
        first_model = next(iter(model_usage), "unknown") if model_usage else "unknown"
        usage = model_usage.get(first_model, {})

        return ClaudeCodeResult(
            output=data.get("result", ""),
            session_id=data.get("session_id", ""),
            exit_code=returncode,
            is_error=data.get("is_error", False),
            duration_seconds=duration,
            raw_json=data,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            cache_read_tokens=usage.get("cacheReadTokens", 0),
            cache_creation_tokens=usage.get("cacheCreationTokens", 0),
            model=first_model,
        )

    async def execute(
        self,
        prompt: str,
        workspace_path: str,
        allowed_tools: list[str] | None = None,
        session_id: str | None = None,
        task_type: str | None = None,
        repo_url: str | None = None,
        repo_branch: str | None = None,
    ) -> ClaudeCodeResult:
        """Execute Claude Code in Podman container."""
        model = None
        if task_type:
            model = self.config.model_routing.get_model(task_type)

        cmd = self._build_command(prompt, workspace_path, allowed_tools, session_id, model, repo_url, repo_branch)

        # Execute with timeout
        import time
        start_time = time.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait with timeout
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.timeout_seconds,
            )

            duration = time.time() - start_time
            return self._parse_result(stdout, stderr, proc.returncode or 0, duration)

        except asyncio.TimeoutError:
            # Kill process and return timeout error
            if proc:
                proc.kill()
                await proc.wait()

            duration = time.time() - start_time
            return ClaudeCodeResult(
                output=f"Execution timed out after {self.config.timeout_seconds}s",
                session_id=session_id or "",
                exit_code=124,  # Standard timeout exit code
                is_error=True,
                duration_seconds=duration,
                raw_json={},
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                model="",
            )

    async def create_session(self, session_id: str, workspace_path: str) -> str:
        """Create a persistent container (not --rm). Returns container name."""
        cmd = ["podman", "run", "-d", "--name", f"claude-session-{session_id}"]
        cmd.extend(self._build_env_args())
        cmd.extend(["-v", f"{workspace_path}:/workspace"])
        cmd.append(self.config.image)
        cmd.extend(["sleep", "infinity"])  # keep alive

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        container_id = stdout.decode().strip()
        return f"claude-session-{session_id}"

    async def execute_in_session(
        self,
        container_name: str,
        prompt: str,
        task_type: str | None = None,
    ) -> ClaudeCodeResult:
        """Execute claude -p inside an EXISTING container using podman exec."""
        model = None
        if task_type:
            model = self.config.model_routing.get_model(task_type)

        args = self._build_base_args(prompt, None, None, model)
        cmd = ["podman", "exec", container_name, "claude"] + args

        import time
        start_time = time.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait with timeout
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.timeout_seconds,
            )

            duration = time.time() - start_time
            return self._parse_result(stdout, stderr, proc.returncode or 0, duration)

        except asyncio.TimeoutError:
            # Don't kill the container — just kill the exec process
            if proc:
                proc.kill()
                await proc.wait()

            duration = time.time() - start_time
            return ClaudeCodeResult(
                output=f"Execution timed out after {self.config.timeout_seconds}s",
                session_id="",
                exit_code=124,
                is_error=True,
                duration_seconds=duration,
                raw_json={},
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                model="",
            )

    async def stop_session(self, container_name: str) -> None:
        """Stop a persistent container (hibernate)."""
        proc = await asyncio.create_subprocess_exec(
            "podman", "stop", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def start_session(self, container_name: str) -> None:
        """Restart a stopped container (resume from hibernate)."""
        proc = await asyncio.create_subprocess_exec(
            "podman", "start", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    async def destroy_session(self, container_name: str) -> None:
        """Remove a container completely."""
        # Stop container first
        await asyncio.create_subprocess_exec(
            "podman", "stop", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Remove container
        proc = await asyncio.create_subprocess_exec(
            "podman", "rm", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
