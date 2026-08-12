"""Temporal workflow for Loop Engineering with durable execution."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

try:
    from temporalio import workflow

    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False

    # Mock workflow decorators for when temporalio is not installed
    class workflow:  # noqa: D101
        @staticmethod
        def defn(cls):  # noqa: D102
            return cls

        @staticmethod
        def run(func):  # noqa: D102
            return func

        @staticmethod
        def signal(func):  # noqa: D102
            return func

        @staticmethod
        def query(func):  # noqa: D102
            return func

        @staticmethod
        async def execute_activity(*args, **kwargs):  # noqa: D102
            raise NotImplementedError("Temporal SDK not installed")

        @staticmethod
        async def wait_condition(condition):  # noqa: D102
            raise NotImplementedError("Temporal SDK not installed")


logger = logging.getLogger(__name__)


@workflow.defn
class LoopEngineeringWorkflow:
    """Durable workflow for Loop Engineering: estimate, plan, implement (loop), deliver.

    Phases:
    1. Cost estimation - estimate cost and get user approval
    2. Planning - create plan and get user review
    3. Implementation - self-correction loop with test-fail-fix cycles
    4. Delivery - final results with user acceptance

    Features:
    - User checkpoints via signals (plan review, cost approval, struggle alerts)
    - Cost circuit breaker - aborts if cumulative cost exceeds budget
    - Struggle detection - alerts user after N consecutive failures
    - Decision log - tracks all user decisions and workflow events
    - Durable state - survives pod crashes and restarts
    """

    def __init__(self) -> None:
        """Initialize workflow state."""
        self.user_response: dict[str, Any] | None = None
        self.status: str = "initializing"
        self.cumulative_cost: float = 0.0
        self.decision_log: list[dict[str, Any]] = []
        self.current_iteration: int = 0

    @workflow.signal
    async def user_responds(self, response: dict[str, Any]) -> None:
        """Receive user response from any channel (Slack, UI, Email).

        Args:
            response: Dict with keys:
                - action: "approve" | "modify" | "cancel" | "continue" | "intervene"
                - feedback: Optional user feedback text
                - channel: "ui" | "slack" | "email" | "webhook"
                - timestamp: ISO 8601 timestamp
        """
        self.user_response = response
        self.decision_log.append(
            {
                "type": response.get("action"),
                "channel": response.get("channel", "unknown"),
                "timestamp": response.get("timestamp"),
                "feedback": response.get("feedback"),
            }
        )

    @workflow.query
    def get_status(self) -> dict[str, Any]:
        """Query current workflow state.

        Used by UI dashboard to display real-time progress.

        Returns:
            Dict with keys:
                - status: Current phase
                - cost: Cumulative cost in USD
                - iteration: Current iteration number
                - decisions: List of decision log entries
        """
        return {
            "status": self.status,
            "cost": self.cumulative_cost,
            "iteration": self.current_iteration,
            "decisions": self.decision_log,
        }

    @workflow.run
    async def run(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute the Loop Engineering workflow.

        Args:
            task: Dict with keys:
                - prompt: User's task description
                - workspace_path: Path to workspace directory
                - max_iterations: Maximum retry attempts (default: 5)
                - max_cost: Budget cap in USD (default: 25.0)
                - struggle_threshold: Failures before user alert (default: 3)
                - task_type: Task classification for model routing

        Returns:
            Dict with keys:
                - status: "complete" | "cancelled" | "cost_exceeded"
                - cost: Total cost in USD
                - iterations: Number of iterations executed
                - decisions: List of all user decisions
                - output: Final output from Claude Code
        """
        if not TEMPORAL_AVAILABLE:
            raise RuntimeError("Temporal SDK not installed")

        from temporalio import workflow as wf

        max_iterations = task.get("max_iterations", 5)
        max_cost = task.get("max_cost", 25.0)
        struggle_threshold = task.get("struggle_threshold", 3)

        workflow_id = task.get("workflow_id", "unknown")
        thread_id = task.get("thread_id", "")

        # ── Phase 1: Cost Estimation ──
        self.status = "estimating"
        logger.info("Starting cost estimation phase")

        await self._emit_status(
            workflow_id, "estimating", "📊 Estimating cost and complexity..."
        )

        estimate = await wf.execute_activity(
            "estimate_cost_activity",
            args=[task],
            start_to_close_timeout=timedelta(seconds=30),
        )

        await self._emit_status(
            workflow_id,
            "cost_ready",
            f"📊 Estimated: {estimate.get('complexity', '?')} complexity, "
            f"${estimate.get('estimated_cost_low', 0):.2f}-${estimate.get('estimated_cost_high', 0):.2f}",
        )

        # Checkpoint: cost approval
        await self._checkpoint("cost_estimate", estimate)

        if self.user_response and self.user_response.get("action") == "cancel":
            logger.info("Workflow cancelled at cost estimate checkpoint")
            return {"status": "cancelled", "cost": 0.0, "decisions": self.decision_log}

        # ── Phase 2: Planning ──
        self.status = "planning"
        logger.info("Starting planning phase")
        await self._emit_status(
            workflow_id, "planning", "📋 Creating implementation plan..."
        )

        plan_result = await wf.execute_activity(
            "run_claude_code_activity",
            args=[
                {
                    "prompt": f"Analyze this task and create a numbered plan. Do NOT implement yet.\n\n{task['prompt']}",
                    "workspace_path": task.get("workspace_path", "/workspace"),
                    "task_type": "planning",
                }
            ],
            start_to_close_timeout=timedelta(minutes=5),
        )

        # Checkpoint: plan review
        await self._checkpoint(
            "plan_review",
            {
                "plan": plan_result.get("output", ""),
                "cost": plan_result.get("cost", 0.0),
            },
        )

        if self.user_response and self.user_response.get("action") == "cancel":
            logger.info("Workflow cancelled at plan review checkpoint")
            return {
                "status": "cancelled",
                "cost": self.cumulative_cost,
                "decisions": self.decision_log,
            }

        # Update prompt with user feedback if modified
        prompt = task["prompt"]
        if self.user_response and self.user_response.get("action") == "modify":
            feedback = self.user_response.get("feedback", "")
            prompt += f"\n\nUSER FEEDBACK: {feedback}"

        # ── Phase 3: Implementation Loop ──
        self.status = "implementing"
        logger.info(
            "Starting implementation phase with max %d iterations", max_iterations
        )

        error_context = ""
        session_id = None
        last_result = None

        for iteration in range(1, max_iterations + 1):
            self.current_iteration = iteration
            logger.info("Starting iteration %d/%d", iteration, max_iterations)

            await self._emit_status(
                workflow_id,
                "implementing",
                f"🔨 Iteration {iteration}/{max_iterations} — Claude Code running in sandbox... (cost so far: ${self.cumulative_cost:.2f})",
            )

            full_prompt = prompt + error_context

            result = await wf.execute_activity(
                "run_claude_code_activity",
                args=[
                    {
                        "prompt": full_prompt,
                        "workspace_path": task.get("workspace_path", "/workspace"),
                        "task_type": task.get("task_type", "implementation"),
                        "session_id": session_id,
                    }
                ],
                start_to_close_timeout=timedelta(minutes=10),
            )

            last_result = result
            iteration_cost = result.get("cost", 0.0)
            self.cumulative_cost += iteration_cost
            session_id = result.get("session_id")

            test_passed = result.get("test_passed", False)
            model = result.get("model", "?")
            tokens = f"{result.get('input_tokens', 0)}/{result.get('output_tokens', 0)}"

            if test_passed:
                await self._emit_status(
                    workflow_id,
                    "iteration_passed",
                    f"✅ Iteration {iteration} passed! model={model} tokens={tokens} cost=${iteration_cost:.4f}",
                )
            else:
                await self._emit_status(
                    workflow_id,
                    "iteration_failed",
                    f"❌ Iteration {iteration} failed. model={model} tokens={tokens} cost=${iteration_cost:.4f} — retrying...",
                )

            logger.info(
                "Iteration %d complete: cost=$%.2f, cumulative=$%.2f, passed=%s",
                iteration,
                iteration_cost,
                self.cumulative_cost,
                test_passed,
            )

            # Cost circuit breaker
            if self.cumulative_cost > max_cost:
                logger.warning(
                    "Cost exceeded: $%.2f > $%.2f", self.cumulative_cost, max_cost
                )
                await self._notify(
                    "cost_exceeded",
                    {
                        "cumulative_cost": self.cumulative_cost,
                        "max_cost": max_cost,
                        "iteration": iteration,
                    },
                )
                return {
                    "status": "cost_exceeded",
                    "cost": self.cumulative_cost,
                    "iterations": iteration,
                    "decisions": self.decision_log,
                    "output": result.get("output", ""),
                }

            # Check if tests passed
            if result.get("test_passed", False):
                logger.info("Tests passed on iteration %d", iteration)
                break

            # Tests failed - check for struggle threshold
            if iteration >= struggle_threshold:
                logger.info("Struggle threshold reached at iteration %d", iteration)
                await self._checkpoint(
                    "struggle_alert",
                    {
                        "iteration": iteration,
                        "max_iterations": max_iterations,
                        "cumulative_cost": self.cumulative_cost,
                        "last_error": result.get("output", "")[-500:],
                    },
                )

                if self.user_response and self.user_response.get("action") == "cancel":
                    logger.info("Workflow cancelled at struggle checkpoint")
                    return {
                        "status": "cancelled",
                        "cost": self.cumulative_cost,
                        "iterations": iteration,
                        "decisions": self.decision_log,
                    }

                # Add user guidance to error context if provided
                if (
                    self.user_response
                    and self.user_response.get("action") == "intervene"
                ):
                    feedback = self.user_response.get("feedback", "")
                    error_context += f"\n\nUSER GUIDANCE: {feedback}"

            # Build error context for next iteration
            error_context = (
                f"\n\nPREVIOUS ATTEMPT {iteration} FAILED:\n"
                f"{result.get('output', '')[-2000:]}\n\n"
                f"Fix the issues. Read existing files first."
            )

        # ── Phase 4: Delivery ──
        self.status = "delivering"
        logger.info("Starting delivery phase")

        await self._checkpoint(
            "delivery",
            {
                "output": last_result.get("output", "") if last_result else "",
                "cost": self.cumulative_cost,
                "iterations": self.current_iteration,
            },
        )

        if self.user_response and self.user_response.get("action") == "cancel":
            logger.info("Workflow cancelled at delivery checkpoint")
            return {
                "status": "cancelled",
                "cost": self.cumulative_cost,
                "iterations": self.current_iteration,
                "decisions": self.decision_log,
            }

        logger.info(
            "Workflow complete: %d iterations, $%.2f total cost",
            self.current_iteration,
            self.cumulative_cost,
        )

        output = last_result.get("output", "") if last_result else ""

        await self._emit_status(
            workflow_id,
            "complete",
            f"🎉 Workflow complete! {self.current_iteration} iterations, ${self.cumulative_cost:.4f} total cost",
        )

        # Post result back to chat thread
        thread_id = task.get("thread_id", "")
        if thread_id:
            try:
                await workflow.execute_activity(
                    "post_result_to_chat_activity",
                    {
                        "thread_id": thread_id,
                        "workflow_id": task.get("workflow_id", ""),
                        "output": output,
                        "cost": self.cumulative_cost,
                        "iterations": self.current_iteration,
                        "status": "complete",
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                )
            except Exception as e:
                logger.warning("Failed to post result to chat: %s", e)

        return {
            "status": "complete",
            "cost": self.cumulative_cost,
            "iterations": self.current_iteration,
            "decisions": self.decision_log,
            "output": output,
        }

    async def _checkpoint(self, checkpoint_type: str, data: dict[str, Any]) -> None:
        """Notify user and wait for response.

        Blocks execution until user responds via signal.

        Args:
            checkpoint_type: Type of checkpoint ("cost_estimate", "plan_review", etc.)
            data: Checkpoint data to send to user
        """
        if not TEMPORAL_AVAILABLE:
            raise RuntimeError("Temporal SDK not installed")

        from temporalio import workflow as wf

        # Notify user
        await wf.execute_activity(
            "notify_user_activity",
            args=[checkpoint_type, data, self.cumulative_cost],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # Reset response and wait for signal
        self.user_response = None
        await wf.wait_condition(lambda: self.user_response is not None)

    async def _emit_status(self, workflow_id: str, phase: str, message: str) -> None:
        """Emit a real-time status update via notify_user_activity."""
        if not TEMPORAL_AVAILABLE:
            return
        from temporalio import workflow as wf

        try:
            await wf.execute_activity(
                "notify_user_activity",
                args=[
                    "progress",
                    {
                        "workflow_id": workflow_id,
                        "phase": phase,
                        "message": message,
                        "status": self.status,
                        "iteration": self.current_iteration,
                        "cost": self.cumulative_cost,
                    },
                    self.cumulative_cost,
                ],
                start_to_close_timeout=timedelta(seconds=10),
            )
        except Exception:
            pass

    async def _notify(self, event_type: str, data: dict[str, Any]) -> None:
        """Notify user without waiting for response.

        Fire-and-forget notification for events that don't require approval.

        Args:
            event_type: Type of event ("cost_exceeded", etc.)
            data: Event data to send to user
        """
        if not TEMPORAL_AVAILABLE:
            raise RuntimeError("Temporal SDK not installed")

        from temporalio import workflow as wf

        await wf.execute_activity(
            "notify_user_activity",
            args=[event_type, data, self.cumulative_cost],
            start_to_close_timeout=timedelta(seconds=30),
        )


@workflow.defn
class CodingSessionWorkflow:
    """Persistent coding session — container stays alive across multiple tasks."""

    def __init__(self) -> None:
        """Initialize session state."""
        self.pending_task: dict[str, Any] | None = None
        self.status: str = "initializing"
        self.tasks_completed: int = 0
        self.total_cost: float = 0.0
        self.container_info: dict[str, Any] | None = None
        self.close_requested: bool = False

    @workflow.signal
    async def submit_task(self, task: dict[str, Any]) -> None:
        """User submits a new task to this session."""
        self.pending_task = task

    @workflow.signal
    async def user_message(self, message: dict[str, Any]) -> None:
        """User sends a message/reply to Claude Code."""
        self.pending_task = {"action": "message", "content": message.get("content", "")}

    @workflow.signal
    async def close_session(self) -> None:
        """User requests session closure."""
        self.close_requested = True
        self.pending_task = {"action": "close"}

    @workflow.query
    def get_session_status(self) -> dict[str, Any]:
        """Query current session status."""
        return {
            "status": self.status,
            "tasks_completed": self.tasks_completed,
            "total_cost": self.total_cost,
            "container": self.container_info,
        }

    @workflow.run
    async def run(self, session: dict[str, Any]) -> dict[str, Any]:
        """Execute the persistent coding session workflow.

        Args:
            session: Dict with keys:
                - session_id: Unique session identifier
                - thread_id: LangGraph thread ID
                - prompt: Initial task prompt
                - task_type: Task classification for model routing
                - task_name: Human-readable task name
                - user_id: User identifier
                - repo_url: Git repository URL (optional)
                - repo_branch: Git branch name (optional)

        Returns:
            Dict with keys:
                - status: "complete" | "hibernated"
                - tasks_completed: Number of tasks processed
                - total_cost: Total cost in USD
        """
        if not TEMPORAL_AVAILABLE:
            raise RuntimeError("Temporal SDK not installed")

        from temporalio import workflow as wf

        self.status = "creating_sandbox"
        thread_id = session.get("thread_id", "")
        session_id = session.get("session_id", "")

        # Phase 1: Create persistent sandbox
        logger.info("Creating persistent sandbox for session %s", session_id)
        self.container_info = await wf.execute_activity(
            "create_sandbox_activity",
            args=[session],
            start_to_close_timeout=timedelta(minutes=5),
        )

        self.status = "ready"

        # Notify user that sandbox is ready
        await wf.execute_activity(
            "notify_user_activity",
            args=[
                "progress",
                {
                    "workflow_id": session_id,
                    "message": "🟢 Sandbox ready. Waiting for tasks...",
                    "status": "ready",
                },
                0.0,
            ],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Phase 2: Process first task (from session args)
        first_prompt = session.get("prompt", "")
        if first_prompt:
            logger.info("Processing initial task for session %s", session_id)
            result = await self._process_task(
                session, first_prompt, session.get("task_type", "implementation")
            )
            # Post result to chat
            if thread_id:
                await wf.execute_activity(
                    "post_result_to_chat_activity",
                    args=[
                        {
                            "thread_id": thread_id,
                            "workflow_id": session_id,
                            "output": result.get("output", ""),
                            "cost": self.total_cost,
                            "iterations": self.tasks_completed,
                            "status": "task_complete",
                        }
                    ],
                    start_to_close_timeout=timedelta(seconds=30),
                )

        # Phase 3: Wait for more tasks
        while not self.close_requested:
            self.status = "idle"
            self.pending_task = None

            try:
                # Wait for next task or idle timeout
                logger.info(
                    "Session %s waiting for next task (idle timeout: 30m)", session_id
                )
                await wf.wait_condition(
                    lambda: self.pending_task is not None,
                    timeout=timedelta(minutes=30),  # idle timeout
                )
            except Exception:
                # Idle timeout — hibernate the CONTAINER but keep WORKFLOW alive
                logger.info(
                    "Session %s idle timeout — hibernating container (workflow stays alive)",
                    session_id,
                )
                self.status = "hibernated"
                await wf.execute_activity(
                    "hibernate_sandbox_activity",
                    args=[self.container_info],
                    start_to_close_timeout=timedelta(seconds=30),
                )
                await wf.execute_activity(
                    "notify_user_activity",
                    args=[
                        "progress",
                        {
                            "workflow_id": session_id,
                            "message": "💤 Container hibernated (30m idle). Send a new task to resume.",
                            "status": "hibernated",
                        },
                        self.total_cost,
                    ],
                    start_to_close_timeout=timedelta(seconds=10),
                )
                # DON'T return — keep waiting. Workflow stays alive in Temporal.
                # User can respond hours/days later via signal.
                # Container will be recreated when needed.
                continue

            if self.close_requested:
                break

            # Process the task
            task = self.pending_task
            if task and task.get("action") == "close":
                break

            self.status = "active"

            # If container was hibernated, recreate it
            if self.status == "active" and self.container_info:
                try:
                    # Try to resume existing container
                    await wf.execute_activity(
                        "create_sandbox_activity",
                        args=[{**session, "session_id": session_id, "resume": True}],
                        start_to_close_timeout=timedelta(minutes=2),
                    )
                    logger.info(
                        "Session %s container resumed from hibernation", session_id
                    )
                except Exception:
                    logger.info(
                        "Session %s creating new container (resume failed)", session_id
                    )
                    self.container_info = await wf.execute_activity(
                        "create_sandbox_activity",
                        args=[session],
                        start_to_close_timeout=timedelta(minutes=5),
                    )

            prompt = task.get("prompt", task.get("content", "")) if task else ""
            task_type = (
                task.get("task_type", "implementation") if task else "implementation"
            )

            logger.info(
                "Processing task %d for session %s",
                self.tasks_completed + 1,
                session_id,
            )
            result = await self._process_task(session, prompt, task_type)

            # Post result to chat
            if thread_id:
                await wf.execute_activity(
                    "post_result_to_chat_activity",
                    args=[
                        {
                            "thread_id": thread_id,
                            "workflow_id": session_id,
                            "output": result.get("output", ""),
                            "cost": self.total_cost,
                            "iterations": self.tasks_completed,
                            "status": "task_complete",
                        }
                    ],
                    start_to_close_timeout=timedelta(seconds=30),
                )

        # Phase 4: Cleanup
        logger.info("Destroying sandbox for session %s", session_id)
        self.status = "destroying"
        await wf.execute_activity(
            "destroy_sandbox_activity",
            args=[{**self.container_info, "cleanup_workspace": False}],
            start_to_close_timeout=timedelta(seconds=30),
        )

        return {
            "status": "complete",
            "tasks_completed": self.tasks_completed,
            "total_cost": self.total_cost,
        }

    async def _process_task(
        self, session: dict[str, Any], prompt: str, task_type: str
    ) -> dict[str, Any]:
        """Process a single task in the persistent session."""
        if not TEMPORAL_AVAILABLE:
            raise RuntimeError("Temporal SDK not installed")

        from temporalio import workflow as wf

        session_id = session.get("session_id", "")

        await wf.execute_activity(
            "notify_user_activity",
            args=[
                "progress",
                {
                    "workflow_id": session_id,
                    "message": f"🔨 Processing task {self.tasks_completed + 1}...",
                    "status": "active",
                },
                self.total_cost,
            ],
            start_to_close_timeout=timedelta(seconds=10),
        )

        result = await wf.execute_activity(
            "execute_in_sandbox_activity",
            args=[
                {
                    "container_name": self.container_info["container_name"],
                    "prompt": prompt
                    + "\n\nNote: Git credentials are pre-configured. You can clone, commit, and push directly.",
                    "task_type": task_type,
                    "permission_mode": session.get("permission_mode", "acceptEdits"),
                }
            ],
            start_to_close_timeout=timedelta(minutes=10),
        )

        self.tasks_completed += 1
        self.total_cost += result.get("cost", 0)

        await wf.execute_activity(
            "notify_user_activity",
            args=[
                "progress",
                {
                    "workflow_id": session_id,
                    "message": f"✅ Task {self.tasks_completed} complete. Cost: ${self.total_cost:.4f}",
                    "status": "task_complete",
                },
                self.total_cost,
            ],
            start_to_close_timeout=timedelta(seconds=10),
        )

        return result
