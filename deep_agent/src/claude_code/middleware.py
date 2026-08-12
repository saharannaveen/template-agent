"""ClaudeCodeExecutionMiddleware — inject claude_code tool, route to Podman runner."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from deep_agent.src.claude_code.config import ClaudeCodeConfig
from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner
from deep_agent.src.claude_code.workflow_store import WorkflowStore

logger = logging.getLogger(__name__)

# Global workflow store instance
_workflow_store = WorkflowStore()


def get_workflow_store() -> WorkflowStore:
    """Get the global workflow store instance.

    Returns:
        WorkflowStore: Global workflow store
    """
    return _workflow_store


def _build_claude_code_tool(config: ClaudeCodeConfig) -> Any:
    """Build the claude_code tool definition for LLM tool binding."""

    @tool
    def claude_code(
        prompt: str,
        repo_url: str = "",
        base_branch: str = "main",
        feature_branch: str = "",
        task_name: str = "code-task",
        task_type: str = "default",
        permission_mode: str = "Auto-Accept Edits",
        workspace: str = "/workspace",
        allowed_tools: list[str] | None = None,
        session_id: str | None = None,
    ) -> str:
        """Run a coding task using Claude Code in an isolated sandbox.

        The sandbox will:
        1. Clone repo_url (if provided)
        2. Checkout base_branch
        3. Create feature_branch from base_branch (if provided)
        4. Execute the prompt (read code, write code, run tests)
        5. Commit and push to feature_branch

        Args:
            prompt: What to do. Be specific — include file paths, requirements, test expectations.
            repo_url: REQUIRED. Full GitHub/GitLab URL, e.g. "https://github.com/org/repo"
            base_branch: Branch to clone/checkout from. Default "main".
            feature_branch: New branch to create for changes. If empty, works on base_branch.
            task_name: Short name for UI progress tracking.
            task_type: Routes to models — planning/design/implementation/test_writing/doc_writing/bug_fix/refactor.
            permission_mode: User's chosen permission level from ask_user.
                Options: "Review Every Change" | "Auto-Accept Edits" | "Auto-Accept Safe" | "Fully Autonomous"
            workspace: Working directory (auto-created).
            allowed_tools: Restrict Claude Code tools.
            session_id: Resume a previous session.

        Returns:
            Execution result with code changes, test results, and usage summary.
        """
        return "This tool is handled by ClaudeCodeExecutionMiddleware"

    return claude_code


def _build_ask_user_tool() -> Any:
    """Build the ask_user tool for structured question interrupts."""

    @tool
    def ask_user(
        message: str,
        questions: list[dict[str, Any]],
    ) -> str:
        """Ask the user structured questions and wait for their answers.

        Use this tool INSTEAD of asking questions in plain text. It renders
        interactive UI controls (buttons, checkboxes, text fields) for the user.

        WHEN TO USE:
        - Before starting any implementation — gather requirements
        - When you need repo URL, branch, framework choice, feature toggles
        - When presenting a plan/architecture for approval (use single_select with Approve/Deny/Request Changes)
        - When offering multiple options for the user to choose from

        Args:
            message: Context message shown above the questions (e.g. "Before I start, I need a few details:")
            questions: List of question objects. Each must have:
                - id: unique identifier (e.g. "repo_url", "framework")
                - text: the question text shown to the user
                - input_type: "text" | "single_select" | "multi_select"
                - options: list of choices (required for single_select and multi_select)
                - placeholder: hint text for text inputs (optional)
                - required: whether answer is required (default true)

        Returns:
            JSON string with the user's answers: {"type": "question_answers", "answers": {"id": "value", ...}}

        Example — gathering requirements:
            ask_user(
                message="Before I start, I need a few details:",
                questions=[
                    {"id": "repo_url", "text": "What's the repository URL?", "input_type": "text", "placeholder": "https://github.com/org/repo.git"},
                    {"id": "branch", "text": "Which branch should I work on?", "input_type": "text", "placeholder": "main"},
                    {"id": "framework", "text": "Which framework?", "input_type": "single_select", "options": ["FastAPI", "Flask", "Django"]},
                    {"id": "features", "text": "Which features should I include?", "input_type": "multi_select", "options": ["Auth", "Tests", "API Docs", "CI/CD", "Docker"]},
                ]
            )

        Example — approval gate:
            ask_user(
                message="Here's my proposed architecture. Review the document above.",
                questions=[
                    {"id": "decision", "text": "How would you like to proceed?", "input_type": "single_select", "options": ["Approve", "Approve All", "Request Changes", "Deny"]}
                ]
            )
        """
        return "This tool is handled by ClaudeCodeExecutionMiddleware"

    return ask_user


_PERMISSION_MODE_MESSAGES = {
    "bypassPermissions": "⚠️ **Agent running in Fully Autonomous mode** after your approval. All edits, commands, and internet access are auto-approved.",
    "acceptEdits": "🔧 **Agent running in Auto-Accept Edits mode.** File reads and edits are auto-approved. Bash commands and internet access will need approval.",
    "auto": "🛡️ **Agent running in Auto-Accept Safe mode.** Only safe operations are auto-approved. Risky operations will need approval.",
    "manual": "🔒 **Agent running in Review Every Change mode.** Every file edit, command, and web request will be shown for your approval.",
}


def _emit_progress(event_type: str, data: dict[str, Any]) -> None:
    """Emit workflow progress event, silently failing if not available."""
    try:
        from deep_agent.src.streaming.progress_events import emit_workflow_progress

        emit_workflow_progress(event_type, data)
    except Exception as exc:
        logger.debug(f"Failed to emit progress event {event_type}: {exc}")


class ClaudeCodeExecutionMiddleware(AgentMiddleware):
    """Inject claude_code tool and route calls to Podman backend."""

    def __init__(self, *, config: ClaudeCodeConfig) -> None:
        """Initialize middleware with execution configuration."""
        self._config = config
        self._runner = PodmanClaudeCodeRunner(config)
        self._claude_code_tool = _build_claude_code_tool(config)
        self._ask_user_tool = _build_ask_user_tool()
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._execution_mode = os.environ.get(
            "CLAUDE_CODE_EXECUTION_MODE", "direct"
        )  # "direct" or "temporal"

    def _get_semaphore(self, org: str) -> asyncio.Semaphore:
        """Get or create a per-org execution semaphore."""
        if org not in self._semaphores:
            self._semaphores[org] = asyncio.Semaphore(
                self._config.max_concurrent_per_org
            )
        return self._semaphores[org]

    def _temporal_available(self) -> bool:
        """Check if Temporal mode is available.

        Returns:
            True if temporalio is installed AND TEMPORAL_HOST is set
        """
        try:
            import temporalio  # noqa: F401

            return bool(os.environ.get("TEMPORAL_HOST"))
        except ImportError:
            return False

    async def _run_via_temporal(
        self,
        args: dict[str, Any],
        tool_call_id: str,
        workflow_id: str,
        task_name: str,
        task_type: str,
        thread_id: str,
        permission_mode: str = "acceptEdits",
    ) -> ToolMessage:
        """Submit to Temporal. Reuses existing session per thread, creates new if none exists."""
        from temporalio.client import Client as TemporalClient

        temporal_host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
        task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "claude-code-workers")
        prompt = args.get("prompt", "")

        try:
            client = await TemporalClient.connect(temporal_host)
            store = get_workflow_store()

            # Check if this thread already has a LIVE session in Temporal
            existing = await store.get_by_thread(thread_id)
            if existing:
                session_id = existing["workflow_id"]
                try:
                    handle = client.get_workflow_handle(session_id)
                    desc = await handle.describe()
                    from temporalio.client import WorkflowExecutionStatus

                    if desc.status == WorkflowExecutionStatus.RUNNING:
                        # Workflow is running — query its session status to verify
                        try:
                            session_status = await handle.query("get_session_status")
                            wf_status = session_status.get("status", "")
                        except Exception:
                            wf_status = "unknown"

                        if wf_status not in ("failed", "destroying"):
                            await handle.signal(
                                "submit_task",
                                {
                                    "prompt": prompt,
                                    "task_type": task_type,
                                    "task_name": task_name,
                                },
                            )
                            logger.info(
                                "Task submitted to existing session: %s (status: %s)",
                                session_id,
                                wf_status,
                            )
                            await store.update_status(
                                session_id, "running", "active", existing.get("cost", 0)
                            )
                            return ToolMessage(
                                content=(
                                    f"✅ **Task submitted to existing session `{session_id}`**\n\n"
                                    f"Your message has been sent to Claude Code inside the sandbox.\n\n"
                                    f"[View Session](/workflows/{session_id})"
                                ),
                                tool_call_id=tool_call_id,
                            )
                        else:
                            logger.info(
                                "Session %s status is %s — creating new",
                                session_id,
                                wf_status,
                            )
                            await handle.terminate("Session in bad state")
                    else:
                        logger.info(
                            "Session %s workflow is %s — creating new",
                            session_id,
                            desc.status.name,
                        )
                    await store.update_status(
                        session_id, "completed", "done", existing.get("cost", 0)
                    )
                except Exception as e:
                    logger.warning("Session %s check failed: %s", session_id, e)
                    await store.update_status(session_id, "failed", "error", 0)

            # Create new persistent session — one per thread
            session_id = workflow_id
            user_id = os.environ.get("USER_ID", "anonymous")

            # Use repo_url/branches from tool args (passed via _run_via_temporal params)
            mode_msg = _PERMISSION_MODE_MESSAGES.get(permission_mode, "")
            _repo_url = args.get("repo_url", "")
            _base_branch = args.get("base_branch", "main")
            _feature_branch = args.get("feature_branch", "")

            # Fallback: extract from prompt if not in args
            if not _repo_url:
                _repo_url, _extracted = PodmanClaudeCodeRunner._extract_repo_url(prompt)
                if _base_branch == "main" and _extracted:
                    _base_branch = _extracted

            logger.info(
                "Creating session: repo=%s base=%s feature=%s",
                _repo_url,
                _base_branch,
                _feature_branch,
            )

            handle = await client.start_workflow(
                "CodingSessionWorkflow",
                {
                    "session_id": session_id,
                    "thread_id": thread_id,
                    "prompt": prompt,
                    "task_type": task_type,
                    "task_name": task_name,
                    "user_id": user_id,
                    "repo_url": _repo_url,
                    "repo_branch": _base_branch,
                    "feature_branch": _feature_branch,
                    "permission_mode": permission_mode,
                },
                id=session_id,
                task_queue=task_queue,
            )

            await store.register(session_id, task_name, user_id, thread_id)
            logger.info(
                "Created new coding session: %s (permission_mode=%s)",
                session_id,
                permission_mode,
            )

            return ToolMessage(
                content=(
                    f"{mode_msg}\n\n"
                    f"✅ **New coding session `{session_id}` created**\n\n"
                    f"A persistent sandbox container is being created for this thread. "
                    f"Claude Code will run inside it. All subsequent messages in this thread "
                    f"go to the same container.\n\n"
                    f"[View Session](/workflows/{session_id})"
                ),
                tool_call_id=tool_call_id,
            )

        except Exception as e:
            logger.error("Temporal submission failed: %s — %s", workflow_id, e)
            return ToolMessage(
                content=f"❌ Failed to submit workflow: {str(e)}",
                tool_call_id=tool_call_id,
            )

    async def _run_direct(
        self,
        args: dict[str, Any],
        tool_call_id: str,
        workflow_id: str,
        task_name: str,
        task_type: str,
        workspace: str,
        workspace_is_temp: bool,
    ) -> ToolMessage:
        """Execute Claude Code directly via PodmanClaudeCodeRunner.

        Args:
            args: Tool call arguments
            tool_call_id: LangChain tool call ID
            workflow_id: Generated workflow ID
            task_name: Task name for tracking
            task_type: Task type for model routing
            workspace: Workspace directory path
            workspace_is_temp: Whether workspace should be cleaned up

        Returns:
            ToolMessage with execution result
        """
        prompt = args.get("prompt", "")
        allowed_tools = args.get("allowed_tools")
        session_id = args.get("session_id")
        model = self._config.model_routing.get_model(task_type)

        # Extract repo info (should be parsed from prompt)
        repo_url = None
        repo_branch = None

        # Add git credential note so Claude Code knows push will work
        prompt += "\n\nNote: Git credentials are pre-configured. You can clone, commit, and push directly without any tokens."

        # Emit subagent_start event with workflow_id and human-readable message
        _emit_progress(
            "subagent_start",
            {
                "workflow_id": workflow_id,
                "task_name": task_name,
                "task_type": task_type,
                "model": model,
                "status": "starting",
                "message": f"Starting Claude Code sandbox: {task_name}",
            },
        )

        started = time.monotonic()
        try:
            # Emit progress event before execution with workflow_id
            _emit_progress(
                "subagent_progress",
                {
                    "workflow_id": workflow_id,
                    "task_name": task_name,
                    "task_type": task_type,
                    "status": "executing",
                    "message": f"Claude Code executing {task_name} using {model}...",
                },
            )

            # Execute Claude Code
            result = await self._runner.execute(
                prompt=prompt,
                workspace_path=workspace,
                allowed_tools=allowed_tools,
                session_id=session_id,
                task_type=task_type,
                repo_url=repo_url if repo_url else None,
                repo_branch=repo_branch if repo_branch else None,
            )

            duration = time.monotonic() - started

            # Compute cost
            cost = result.compute_cost(self._config.cost.pricing)

            # Log execution
            logger.info(
                "Claude Code execution completed",
                extra={
                    "workflow_id": workflow_id,
                    "task_name": task_name,
                    "task_type": task_type,
                    "model": result.model,
                    "duration_seconds": duration,
                    "cost_usd": cost,
                    "tokens_in": result.input_tokens,
                    "tokens_out": result.output_tokens,
                    "exit_code": result.exit_code,
                    "is_error": result.is_error,
                },
            )

            # Update workflow store
            status = "error" if result.is_error else "complete"
            await _workflow_store.update_status(
                workflow_id=workflow_id,
                status=status,
                phase="complete",
                cost=cost,
                iterations=1,
            )

            # Emit subagent_end event with workflow_id and detailed summary
            _emit_progress(
                "subagent_end",
                {
                    "workflow_id": workflow_id,
                    "task_name": task_name,
                    "task_type": task_type,
                    "model": result.model,
                    "duration_seconds": duration,
                    "cost_usd": cost,
                    "status": "complete",
                    "message": f"Completed {task_name}: {result.model} | {result.input_tokens}/{result.output_tokens} tokens | ${cost:.4f} | {duration:.1f}s",
                },
            )

            # Build response content with usage summary and workflow link
            workflow_link = f"\n\n[View Workflow](/workflows/{workflow_id})"
            usage_summary = (
                f"\n\n---\n📊 **Usage:** model={result.model} | "
                f"tokens={result.input_tokens}/{result.output_tokens} | "
                f"cost=${cost:.4f} | duration={duration:.1f}s{workflow_link}"
            )
            content = result.output + usage_summary

            # Build ToolMessage with full result in additional_kwargs
            return ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
                additional_kwargs={"claude_code_result": asdict(result)},
            )

        except Exception as exc:
            duration = time.monotonic() - started
            logger.error(
                "Claude Code execution failed",
                extra={
                    "workflow_id": workflow_id,
                    "task_name": task_name,
                    "task_type": task_type,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "duration_seconds": duration,
                },
            )

            # Update workflow store with error
            await _workflow_store.update_status(
                workflow_id=workflow_id,
                status="error",
                phase="failed",
                cost=0.0,
                iterations=1,
            )

            # Emit failure event with workflow_id
            _emit_progress(
                "subagent_end",
                {
                    "workflow_id": workflow_id,
                    "task_name": task_name,
                    "task_type": task_type,
                    "error": str(exc),
                    "duration_seconds": duration,
                    "status": "failed",
                    "message": f"Failed {task_name}: {type(exc).__name__} - {str(exc)}",
                },
            )

            return ToolMessage(
                content=f"Claude Code execution failed: {type(exc).__name__}",
                tool_call_id=tool_call_id,
            )
        finally:
            if workspace_is_temp:
                import shutil

                shutil.rmtree(workspace, ignore_errors=True)

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Any
    ) -> ModelResponse[Any]:
        """Synchronous model call pass-through."""
        return handler(request)

    async def awrap_model_call(
        self, request: ModelRequest[Any], handler: Any
    ) -> ModelResponse[Any]:
        """Inject the claude_code tool into model requests when enabled."""
        if not self._config.enabled:
            return await handler(request)
        updated = request.override(
            tools=[*request.tools, self._claude_code_tool, self._ask_user_tool]
        )
        return await handler(updated)

    @staticmethod
    async def _is_container_running(container_name: str) -> bool:
        """Check if a podman container is running."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "podman",
                "inspect",
                container_name,
                "--format",
                "{{.State.Running}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return stdout.decode().strip().lower() == "true"
        except Exception:
            return False

    async def _handle_ask_user(self, tool_call: dict[str, Any]) -> ToolMessage:
        """Handle ask_user tool calls by emitting a LangGraph interrupt."""
        args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id", "")
        message = args.get("message", "")
        questions = args.get("questions", [])

        if not questions:
            return ToolMessage(
                content="No questions provided",
                tool_call_id=tool_call_id,
            )

        from langgraph.types import interrupt

        interrupt_payload = {
            "type": "clarifying_questions",
            "message": message,
            "questions": questions,
        }

        user_response = interrupt(interrupt_payload)

        if isinstance(user_response, str):
            return ToolMessage(content=user_response, tool_call_id=tool_call_id)

        return ToolMessage(
            content=str(user_response) if user_response else "No response from user",
            tool_call_id=tool_call_id,
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """Synchronous tool call pass-through."""
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """Intercept claude_code and ask_user tool calls."""
        tool_call = request.tool_call
        tool_name = tool_call.get("name")

        if tool_name == "ask_user":
            return await self._handle_ask_user(tool_call)

        if tool_name != "claude_code":
            return await handler(request)

        args = tool_call.get("args", {})
        prompt = args.get("prompt", "")
        repo_url = args.get("repo_url", "")
        base_branch = args.get("base_branch", "main")
        feature_branch = args.get("feature_branch", "")
        task_name = args.get("task_name", "code-task")
        task_type = args.get("task_type", "default")
        tool_call_id = tool_call.get("id", "")

        # Fallback: extract repo URL from prompt if not provided as parameter
        if not repo_url:
            repo_url, extracted_branch = PodmanClaudeCodeRunner._extract_repo_url(
                prompt
            )
            if not base_branch or base_branch == "main":
                base_branch = extracted_branch or "main"

        logger.info(
            "claude_code: repo=%s base=%s feature=%s",
            repo_url,
            base_branch,
            feature_branch,
        )

        if not prompt.strip():
            return ToolMessage(
                content="No prompt provided for Claude Code task",
                tool_call_id=tool_call_id,
            )

        # Permission mode from LLM (set via ask_user before calling claude_code)
        permission_mode_map = {
            "Review Every Change": "manual",
            "Auto-Accept Edits": "acceptEdits",
            "Auto-Accept Safe": "auto",
            "Fully Autonomous": "bypassPermissions",
        }
        raw_mode = args.get("permission_mode", "")
        cli_permission_mode = (
            permission_mode_map.get(raw_mode, raw_mode) if raw_mode else "acceptEdits"
        )
        if cli_permission_mode not in (
            "manual",
            "acceptEdits",
            "auto",
            "bypassPermissions",
        ):
            cli_permission_mode = "acceptEdits"
        logger.info(
            "claude_code called: task=%s type=%s permission_mode=%s",
            task_name,
            task_type,
            cli_permission_mode,
        )

        org = os.environ.get("AI_PLATFORM_AGENT_ORG", "default")
        semaphore = self._get_semaphore(org)

        # Acquire semaphore with timeout
        acquired = False
        try:
            await asyncio.wait_for(
                semaphore.acquire(),
                timeout=self._config.queue_timeout_seconds,
            )
            acquired = True
        except asyncio.TimeoutError:
            return ToolMessage(
                content="Claude Code execution queue full, try again later",
                tool_call_id=tool_call_id,
            )

        import uuid

        workflow_id = f"wf-{uuid.uuid4().hex[:8]}"
        user_id = os.environ.get("USER_ID", "anonymous")

        # Extract thread_id from LangGraph config
        thread_id = ""
        try:
            from langgraph.config import get_config

            config = get_config()
            thread_id = config.get("configurable", {}).get("thread_id", "")
        except Exception:
            logger.debug("Could not extract thread_id from LangGraph config")

        # Execute via Temporal — register happens inside only for NEW sessions
        try:
            if not self._temporal_available():
                return ToolMessage(
                    content="Temporal server not available. Set TEMPORAL_HOST env var and ensure Temporal is running.",
                    tool_call_id=tool_call_id,
                )
            return await self._run_via_temporal(
                args,
                tool_call_id,
                workflow_id,
                task_name,
                task_type,
                thread_id,
                permission_mode=cli_permission_mode,
            )
        finally:
            if acquired:
                semaphore.release()
