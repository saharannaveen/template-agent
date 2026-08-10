"""ClaudeCodeExecutionMiddleware — inject claude_code tool, route to Podman runner."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
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
        task_name: str = "code-task",
        task_type: str = "default",
        workspace: str = "/workspace",
        allowed_tools: list[str] | None = None,
        session_id: str | None = None,
    ) -> str:
        """Run a coding task using Claude Code in an isolated sandbox.

        IMPORTANT — Before calling this tool, you MUST:

        1. GATHER REQUIREMENTS: Check the user's message carefully. If ANY of these are missing or contain [REDACTED], you MUST ask the user before proceeding:
           - What to build/fix (the task description)
           - GitHub/GitLab repo URL — REQUIRED if user mentions push/commit/branch/repo. Must be a full URL like https://github.com/org/repo.git. If missing or shows [REDACTED], ask: "Please provide the full GitHub repository URL (e.g., https://github.com/your-org/your-repo.git)"
           - Branch name — ask: "What branch should I create/use?"
           Do NOT proceed if the repo URL is missing, redacted, or unclear.

        2. ANALYZE & ESTIMATE: Before calling, tell the user:
           - What steps you'll perform (plan, design, implement, test)
           - Which model will be used per step (based on task_type):
             * planning/test_writing/doc_writing/refactor → Sonnet ($3/MTok in, $15/MTok out)
             * design/implementation/bug_fix → Opus ($15/MTok in, $75/MTok out)
           - Estimated tokens based on complexity:
             * Simple (1-2 files): ~5K in / 2K out → ~$0.20
             * Medium (multi-file + tests): ~40K in / 15K out → ~$1.70-$3.40
             * Complex (full app): ~80K in / 30K out → ~$3.50-$10.50
           - Ask: "Estimated cost is $X-$Y. Shall I proceed?"

        3. ONLY call this tool AFTER the user approves the estimate.

        Args:
            prompt: Full instructions including repo URL and branch if provided by user.
            task_name: Short name for UI progress tracking.
            task_type: Routes to different models — planning/design/implementation/test_writing/doc_writing/bug_fix/refactor/default.
            workspace: Working directory (auto-created).
            allowed_tools: Restrict Claude Code tools.
            session_id: Resume a previous session.
        Returns:
            Execution result with code changes, test results, and usage summary.
        """
        return "This tool is handled by ClaudeCodeExecutionMiddleware"

    return claude_code


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
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._execution_mode = os.environ.get("CLAUDE_CODE_EXECUTION_MODE", "direct")  # "direct" or "temporal"

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
    ) -> ToolMessage:
        """Submit to Temporal and return IMMEDIATELY. Result comes via notification."""
        from temporalio.client import Client as TemporalClient

        temporal_host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
        temporal_url = f"http://localhost:8233/namespaces/default/workflows/{workflow_id}"

        try:
            client = await TemporalClient.connect(temporal_host)

            # Check if this thread already has an active session
            store = get_workflow_store()
            existing = await store.get_by_thread(thread_id)

            if existing and existing.get("status") in ("running", "ready", "idle", "active"):
                # Reuse existing session — submit task as signal
                session_id = existing["workflow_id"]
                handle = client.get_workflow_handle(session_id)
                await handle.signal("submit_task", {
                    "prompt": args.get("prompt", ""),
                    "task_type": task_type,
                    "task_name": task_name,
                })

                logger.info("Task submitted to existing session: %s", session_id)

                return ToolMessage(
                    content=(
                        f"✅ **Task submitted to existing session**\n\n"
                        f"- **Session ID:** `{session_id}`\n"
                        f"- **Task:** {task_name}\n"
                        f"- **Temporal Dashboard:** [{session_id}]({f'http://localhost:8233/namespaces/default/workflows/{session_id}'})\n"
                        f"- **Status:** Processing\n\n"
                        f"The task is now executing in your existing sandbox. "
                        f"You'll be notified when it completes.\n\n"
                        f"[View Session](/workflows/{session_id})"
                    ),
                    tool_call_id=tool_call_id,
                )
            else:
                # Create new persistent session
                session_id = workflow_id
                user_id = os.environ.get("USER_ID", "anonymous")

                handle = await client.start_workflow(
                    "CodingSessionWorkflow",
                    {
                        "session_id": session_id,
                        "thread_id": thread_id,
                        "prompt": args.get("prompt", ""),
                        "task_type": task_type,
                        "task_name": task_name,
                        "user_id": user_id,
                        "repo_url": "",  # extracted by runner
                        "repo_branch": "",
                    },
                    id=session_id,
                    task_queue="claude-code-workers",
                )

                await store.register(session_id, task_name, user_id, thread_id)

                logger.info("Created new coding session: %s (run_id=%s)", session_id, handle.result_run_id)

                return ToolMessage(
                    content=(
                        f"✅ **New coding session created**\n\n"
                        f"- **Session ID:** `{session_id}`\n"
                        f"- **Task:** {task_name}\n"
                        f"- **Temporal Dashboard:** [{session_id}]({temporal_url})\n"
                        f"- **Status:** Creating sandbox\n\n"
                        f"A persistent sandbox is being created. The container will stay alive "
                        f"for future tasks in this thread. You'll be notified when the first task completes.\n\n"
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
        updated = request.override(tools=[*request.tools, self._claude_code_tool])
        return await handler(updated)

    def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """Synchronous tool call pass-through."""
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """Intercept claude_code tool calls and route to Podman backend."""
        tool_call = request.tool_call
        if tool_call.get("name") != "claude_code":
            return await handler(request)

        args = tool_call.get("args", {})
        prompt = args.get("prompt", "")
        task_name = args.get("task_name", "code-task")
        task_type = args.get("task_type", "default")
        base_dir = os.path.expanduser("~/.claude-workspaces")
        os.makedirs(base_dir, exist_ok=True)
        workspace = tempfile.mkdtemp(prefix="task-", dir=base_dir)
        workspace_is_temp = True
        allowed_tools = args.get("allowed_tools")
        session_id = args.get("session_id")
        tool_call_id = tool_call.get("id", "")

        if not prompt.strip():
            return ToolMessage(
                content="No prompt provided for Claude Code task",
                tool_call_id=tool_call_id,
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

        # Generate workflow ID and register in store
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

        await _workflow_store.register(
            workflow_id=workflow_id, task_name=task_name, user_id=user_id, thread_id=thread_id
        )

        # Execute ONLY via Temporal
        try:
            if not self._temporal_available():
                return ToolMessage(
                    content="Temporal server not available. Set TEMPORAL_HOST env var and ensure Temporal is running.",
                    tool_call_id=tool_call_id,
                )
            return await self._run_via_temporal(
                args, tool_call_id, workflow_id, task_name, task_type, thread_id
            )
        finally:
            if acquired:
                semaphore.release()
