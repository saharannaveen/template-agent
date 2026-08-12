"""Temporal activities that wrap Phase 1 Claude Code components."""

from __future__ import annotations

import logging
from typing import Any

try:
    from temporalio import activity

    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False

    # Mock activity decorator when temporalio is not installed
    class activity:  # noqa: D101
        @staticmethod
        def defn(func):  # noqa: D102
            return func


from deep_agent.src.claude_code.config import ClaudeCodeConfig
from deep_agent.src.claude_code.cost_estimator import estimate_cost
from deep_agent.src.claude_code.runner import PodmanClaudeCodeRunner

logger = logging.getLogger(__name__)


@activity.defn
async def estimate_cost_activity(task: dict[str, Any]) -> dict[str, Any]:
    """Estimate cost for a Claude Code task.

    Wraps the Phase 1 cost_estimator.estimate_cost() function.

    Args:
        task: Dict with keys:
            - prompt: User's task description
            - max_iterations: Maximum iterations allowed
            - pricing: Optional pricing override

    Returns:
        Dict with keys:
            - complexity: "trivial" | "simple" | "medium" | "complex"
            - estimated_cost_low: Low-end estimate in USD
            - estimated_cost_high: High-end estimate in USD
            - max_possible_cost: Maximum possible cost in USD
    """
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    logger.info("Estimating cost for task: %s", task.get("prompt", "")[:100])

    # Use default pricing if not provided
    pricing = task.get(
        "pricing",
        {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            },
        },
    )

    max_iterations = task.get("max_iterations", 5)

    result = estimate_cost(
        prompt=task["prompt"],
        pricing=pricing,
        max_iterations=max_iterations,
    )

    logger.info(
        "Cost estimate: %s, $%.2f-$%.2f",
        result["complexity"],
        result["estimated_cost_low"],
        result["estimated_cost_high"],
    )

    return result


@activity.defn
async def run_claude_code_activity(args: dict[str, Any]) -> dict[str, Any]:
    """Execute Claude Code in a sandbox.

    Wraps the Phase 1 PodmanClaudeCodeRunner.execute() method.

    Args:
        args: Dict with keys:
            - prompt: Task prompt for Claude Code
            - workspace_path: Path to workspace directory
            - task_type: Optional task type for model routing
            - session_id: Optional session ID for --resume
            - allowed_tools: Optional list of allowed tools

    Returns:
        Dict with keys:
            - output: Claude Code output text
            - session_id: Session ID for resuming
            - exit_code: Process exit code
            - is_error: Whether execution resulted in error
            - duration_seconds: Execution duration
            - test_passed: Whether tests passed (three-signal detection)
            - cost: Cost in USD
            - input_tokens: Input token count
            - output_tokens: Output token count
            - model: Model used
    """
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    logger.info("Running Claude Code: %s", args.get("prompt", "")[:100])

    import os
    import tempfile

    config = ClaudeCodeConfig(
        enabled=True,
        runner="podman",
        image="claude-sandbox:v2.1.224",
        timeout_seconds=600,
    )

    # Create workspace on host (must be under home dir for Podman macOS)
    base_dir = os.path.expanduser("~/.claude-workspaces")
    os.makedirs(base_dir, exist_ok=True)
    workspace_path = tempfile.mkdtemp(prefix="temporal-", dir=base_dir)

    # Inject user memory/preferences into workspace
    user_id = args.get("user_id", "default")
    memory_dir = os.path.expanduser(f"~/.claude-memories/{user_id}")
    claude_dir = os.path.join(workspace_path, ".claude", "memory")
    os.makedirs(claude_dir, exist_ok=True)
    if os.path.isdir(memory_dir):
        import shutil

        for f in os.listdir(memory_dir):
            src = os.path.join(memory_dir, f)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(claude_dir, f))
        logger.info(
            "Injected %d memory files for user %s", len(os.listdir(memory_dir)), user_id
        )

    # Create CLAUDE.md with project instructions
    claude_md = os.path.join(workspace_path, "CLAUDE.md")
    with open(claude_md, "w") as f:
        f.write("# Loop Engineering Agent\n\n")
        f.write("You are an autonomous coding agent running in an isolated sandbox.\n")
        f.write(
            "Git credentials are pre-configured. Clone, commit, and push directly.\n"
        )
        f.write("Always run tests before pushing. Follow the user's coding style.\n")
        f.write(f"User: {user_id}\n")

    runner = PodmanClaudeCodeRunner(config)

    prompt = args["prompt"]
    prompt += "\n\nNote: Git credentials are pre-configured. You can clone, commit, and push directly without any tokens."
    prompt += "\nA CLAUDE.md file exists in /workspace with project instructions. Read it first."

    try:
        result = await runner.execute(
            prompt=prompt,
            workspace_path=workspace_path,
            allowed_tools=args.get("allowed_tools"),
            session_id=args.get("session_id"),
            task_type=args.get("task_type"),
        )
    finally:
        # Extract new learnings from sandbox before cleanup
        sandbox_memory = os.path.join(workspace_path, ".claude", "memory")
        if os.path.isdir(sandbox_memory):
            os.makedirs(memory_dir, exist_ok=True)
            for f in os.listdir(sandbox_memory):
                src = os.path.join(sandbox_memory, f)
                if os.path.isfile(src):
                    import shutil

                    shutil.copy2(src, os.path.join(memory_dir, f))
            logger.info(
                "Extracted %d memory files from sandbox for user %s",
                len(os.listdir(sandbox_memory)),
                user_id,
            )

        # Cleanup workspace
        import shutil

        shutil.rmtree(workspace_path, ignore_errors=True)

    # Compute cost using config pricing
    cost = result.compute_cost(config.cost.pricing)

    # Get test result using three-signal detection
    test_result = result.test_result

    logger.info(
        "Claude Code complete: exit_code=%d, test_passed=%s, cost=$%.2f",
        result.exit_code,
        test_result.passed,
        cost,
    )

    return {
        "output": result.output,
        "session_id": result.session_id,
        "exit_code": result.exit_code,
        "is_error": result.is_error,
        "duration_seconds": result.duration_seconds,
        "test_passed": test_result.passed,
        "test_signal": test_result.signal,
        "cost": cost,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "model": result.model,
    }


@activity.defn
async def notify_user_activity(
    event_type: str,
    data: dict[str, Any],
    cumulative_cost: float,
) -> None:
    """Notify user via all configured channels.

    Dispatches to:
    - Chat UI via SSE/Redis
    - Slack via Bot API (if configured)
    - Email via SMTP (if configured)
    - Webhook via HTTP (if configured)

    Args:
        event_type: Type of event ("checkpoint", "completion", "struggle", "cost_alert")
        data: Event-specific data (must include workflow_id, task_name, message)
        cumulative_cost: Current cumulative cost in USD
    """
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    logger.info(
        "Notifying user: event=%s, cost=$%.2f, data=%s",
        event_type,
        cumulative_cost,
        str(data)[:100],
    )

    # Build notification object
    from deep_agent.src.claude_code.notifications.models import (
        Notification,
        NotificationChannelsConfig,
        NotificationConfig,
    )
    from deep_agent.src.claude_code.notifications.router import NotificationRouter

    notification = Notification(
        type=event_type,  # type: ignore
        workflow_id=data.get("workflow_id", "unknown"),
        task_name=data.get("task_name", "task"),
        message=data.get("message", ""),
        data=data,
        cumulative_cost=cumulative_cost,
        actions=data.get("actions", []),
    )

    # Build config from environment
    import os

    config = NotificationConfig(
        channels=NotificationChannelsConfig(
            chat_ui={
                "enabled": True,
                "redis_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            },
            slack={
                "enabled": bool(os.environ.get("SLACK_BOT_TOKEN")),
                "bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
                "default_channel": os.environ.get(
                    "SLACK_DEFAULT_CHANNEL", "#loop-engineering"
                ),
            },
            webhook={
                "enabled": bool(os.environ.get("WEBHOOK_URL")),
                "url": os.environ.get("WEBHOOK_URL", ""),
            },
        )
    )

    # Send via router
    router = NotificationRouter(config)
    await router.notify(notification)

    # Update WorkflowStore so GET /api/workflows returns data
    try:
        from deep_agent.src.claude_code.workflow_store import WorkflowStore

        store = WorkflowStore()
        workflow_id = data.get("workflow_id", "")
        status = data.get("status", "running")
        phase = data.get("phase", data.get("status", "unknown"))
        user_id = data.get("user_id", "anonymous")
        thread_id = data.get("thread_id", "")
        iteration = data.get("iteration", 0)

        existing = await store.get(workflow_id)
        if existing is None and workflow_id:
            await store.register(
                workflow_id=workflow_id,
                task_name=data.get("task_name", "task"),
                user_id=user_id,
                thread_id=thread_id or None,
            )
        if workflow_id:
            await store.update_status(
                workflow_id=workflow_id,
                status=status,
                phase=phase,
                cost=cumulative_cost,
                iterations=iteration if iteration else None,
            )
    except Exception as e:
        logger.warning("Failed to update WorkflowStore: %s", e)

    logger.info("User notification sent: %s", event_type)


@activity.defn
async def post_result_to_chat_activity(args: dict[str, Any]) -> None:
    """Post workflow result back to the chat thread via agent API."""
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    import os

    import httpx

    thread_id = args.get("thread_id", "")
    workflow_id = args.get("workflow_id", "")
    output = args.get("output", "No output")
    cost = args.get("cost", 0)
    iterations = args.get("iterations", 0)
    status = args.get("status", "complete")

    agent_url = os.environ.get("AGENT_URL", "http://localhost:5002")
    temporal_url = f"http://localhost:8233/namespaces/default/workflows/{workflow_id}"

    message = (
        f"## ✅ Workflow Complete: `{workflow_id}`\n\n"
        f"{output[:2000]}\n\n"
        f"---\n"
        f"📊 **Iterations:** {iterations} | **Cost:** ${cost:.4f} | "
        f"**Temporal:** [{workflow_id}]({temporal_url})\n"
        f"[View Workflow](/workflows/{workflow_id})"
    )

    if not thread_id:
        logger.warning("No thread_id provided — cannot post result to chat")
        return

    try:
        async with httpx.AsyncClient() as client:
            # Post result as a new run on the thread
            resp = await client.post(
                f"{agent_url}/threads/{thread_id}/runs",
                json={
                    "assistant_id": "agent",
                    "input": {"messages": [{"role": "assistant", "content": message}]},
                },
                timeout=10.0,
            )
            logger.info(
                "Posted result to thread %s: status=%d", thread_id, resp.status_code
            )
    except Exception as e:
        logger.error("Failed to post result to chat: %s", e)


@activity.defn
async def create_sandbox_activity(session: dict[str, Any]) -> dict[str, Any]:
    """Create a persistent sandbox container for a coding session.

    Args:
        session: Dict with keys:
            - session_id: Unique session identifier
            - user_id: User identifier
            - repo_url: Optional git repository URL
            - repo_branch: Optional git branch name

    Returns:
        Dict with keys:
            - container_name: Podman container name
            - container_id: Podman container ID
            - workspace_path: Host workspace path
    """
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    import os
    import subprocess
    import tempfile

    session_id = session.get("session_id", "unknown")
    user_id = session.get("user_id", "default")
    container_name = f"claude-session-{session_id}"

    logger.info("Creating persistent sandbox: %s", container_name)

    # Create workspace on host
    base_dir = os.path.expanduser("~/.claude-workspaces")
    os.makedirs(base_dir, exist_ok=True)
    workspace_path = tempfile.mkdtemp(prefix=f"session-{session_id}-", dir=base_dir)

    # Inject user memory
    memory_dir = os.path.expanduser(f"~/.claude-memories/{user_id}")
    claude_dir = os.path.join(workspace_path, ".claude", "memory")
    os.makedirs(claude_dir, exist_ok=True)
    if os.path.isdir(memory_dir):
        import shutil

        for f in os.listdir(memory_dir):
            src = os.path.join(memory_dir, f)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(claude_dir, f))
        logger.info(
            "Injected %d memory files for user %s", len(os.listdir(memory_dir)), user_id
        )

    # Create CLAUDE.md
    claude_md = os.path.join(workspace_path, "CLAUDE.md")
    with open(claude_md, "w") as f:
        f.write("# Persistent Coding Session\n\n")
        f.write(
            "You are running in a persistent sandbox that will handle multiple tasks.\n"
        )
        f.write(
            "Git credentials are pre-configured. Clone, commit, and push directly.\n"
        )
        f.write("Always run tests before pushing. Follow the user's coding style.\n")
        f.write(f"User: {user_id}\n")

    # Start container
    image = os.environ.get("CLAUDE_CODE_IMAGE", "claude-sandbox:v2.1.224")

    # Persistent .claude directory for sessions, plugins, settings
    claude_home = os.path.expanduser(f"~/.claude-homes/{user_id}")
    os.makedirs(claude_home, exist_ok=True)

    cmd = [
        "podman",
        "run",
        "-d",
        "--name",
        container_name,
        "-v",
        f"{workspace_path}:/workspace:rw",
        "-v",
        f"{claude_home}:/home/agent/.claude:rw",  # Persist sessions, plugins, settings
        "-w",
        "/workspace",
    ]

    # Auth env vars
    for env_key in [
        "CLAUDE_CODE_USE_VERTEX",
        "ANTHROPIC_VERTEX_PROJECT_ID",
        "GITHUB_TOKEN",
        "GITLAB_TOKEN",
    ]:
        val = os.environ.get(env_key, "")
        if val:
            cmd.extend(["-e", f"{env_key}={val}"])

    # GCP credentials
    gcp_adc = os.path.expanduser(
        "~/.config/gcloud/application_default_credentials.json"
    )
    if os.path.exists(gcp_adc):
        cmd.extend(
            [
                "-e",
                "GOOGLE_APPLICATION_CREDENTIALS=/gcp/application_default_credentials.json",
            ]
        )
        cmd.extend(["-v", f"{gcp_adc}:/gcp/application_default_credentials.json:ro"])

    # Plugins config
    plugins = os.environ.get("CLAUDE_PLUGINS", "")
    if plugins:
        cmd.extend(["-e", f"CLAUDE_PLUGINS={plugins}"])

    # MCP config
    mcp_config = os.environ.get("MCP_CONFIG", "")
    if mcp_config:
        cmd.extend(["-e", f"MCP_CONFIG={mcp_config}"])

    # Repo env vars (for entrypoint auto-clone)
    repo_url = session.get("repo_url", "")
    repo_branch = session.get("repo_branch", "")
    if repo_url:
        cmd.extend(["-e", f"REPO_URL={repo_url}"])
    if repo_branch:
        cmd.extend(["-e", f"REPO_BRANCH={repo_branch}"])

    # NO --rm — container persists for session reuse
    cmd.extend([image, "sleep", "infinity"])

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    container_id = result.stdout.strip()
    logger.info(
        "Created container %s (id: %s) with claude_home=%s",
        container_name,
        container_id[:12],
        claude_home,
    )

    return {
        "container_name": container_name,
        "container_id": container_id,
        "workspace_path": workspace_path,
        "claude_home": claude_home,
    }


@activity.defn
async def execute_in_sandbox_activity(args: dict[str, Any]) -> dict[str, Any]:
    """Execute Claude Code in an existing sandbox container.

    Args:
        args: Dict with keys:
            - container_name: Name of the running container
            - prompt: Task prompt for Claude Code
            - task_type: Optional task type for model routing

    Returns:
        Dict with keys:
            - output: Claude Code output text
            - exit_code: Process exit code
            - is_error: Whether execution resulted in error
            - cost: Cost in USD
            - input_tokens: Input token count
            - output_tokens: Output token count
            - model: Model used
    """
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    import subprocess

    container_name = args["container_name"]
    prompt = args["prompt"]
    task_type = args.get("task_type", "implementation")

    logger.info("Executing in sandbox %s: %s", container_name, prompt[:100])

    # Write prompt to a temp file in container
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    try:
        # Copy prompt to container
        subprocess.run(
            ["podman", "cp", prompt_file, f"{container_name}:/tmp/prompt.txt"],
            check=True,
        )

        # Execute claude-code in container
        result = subprocess.run(
            [
                "podman",
                "exec",
                container_name,
                "claude-code",
                "--prompt-file",
                "/tmp/prompt.txt",
                "--task-type",
                task_type,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        output = result.stdout
        exit_code = result.returncode

        # Parse usage from output (simplified - should use structured output)
        # For now, return mock values
        logger.info("Sandbox execution complete: exit_code=%d", exit_code)

        return {
            "output": output,
            "exit_code": exit_code,
            "is_error": exit_code != 0,
            "cost": 0.15,  # Mock - should parse from output
            "input_tokens": 5000,
            "output_tokens": 2000,
            "model": "claude-opus-4",
        }

    finally:
        import os

        os.unlink(prompt_file)


@activity.defn
async def hibernate_sandbox_activity(container_info: dict[str, Any]) -> None:
    """Hibernate (pause) a sandbox container to save resources.

    Args:
        container_info: Dict with container_name key
    """
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    import subprocess

    container_name = container_info["container_name"]
    logger.info("Hibernating sandbox: %s", container_name)

    subprocess.run(
        ["podman", "pause", container_name],
        check=True,
    )


@activity.defn
async def destroy_sandbox_activity(container_info: dict[str, Any]) -> None:
    """Destroy a sandbox container and optionally clean up workspace.

    Args:
        container_info: Dict with keys:
            - container_name: Container name
            - workspace_path: Host workspace path
            - cleanup_workspace: Whether to delete workspace (default: False)
    """
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    import subprocess

    container_name = container_info["container_name"]
    workspace_path = container_info.get("workspace_path", "")
    cleanup_workspace = container_info.get("cleanup_workspace", False)

    logger.info("Destroying sandbox: %s", container_name)

    # Stop and remove container (--rm flag will auto-remove)
    subprocess.run(
        ["podman", "stop", container_name],
        check=False,  # Don't fail if already stopped
    )

    # Optionally clean up workspace
    if cleanup_workspace and workspace_path:
        import shutil

        logger.info("Cleaning up workspace: %s", workspace_path)
        shutil.rmtree(workspace_path, ignore_errors=True)


@activity.defn
async def create_sandbox_activity(session: dict[str, Any]) -> dict[str, Any]:
    """Create persistent sandbox: container + workspace + clone + deps."""
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    import os
    import shutil

    session_id = session["session_id"]
    user_id = session.get("user_id", "default")
    repo_url = session.get("repo_url", "")
    repo_branch = session.get("repo_branch", "")  # base branch to clone
    feature_branch = session.get("feature_branch", "")  # new branch for changes

    logger.info(
        "Creating persistent sandbox: session=%s repo=%s base=%s feature=%s",
        session_id,
        repo_url,
        repo_branch,
        feature_branch,
    )

    # Create persistent workspace
    workspace = os.path.expanduser(f"~/.claude-workspaces/session-{session_id}")
    os.makedirs(workspace, exist_ok=True)

    # Inject user memories
    memory_dir = os.path.expanduser(f"~/.claude-memories/{user_id}")
    claude_dir = os.path.join(workspace, ".claude", "memory")
    os.makedirs(claude_dir, exist_ok=True)
    if os.path.isdir(memory_dir):
        for f in os.listdir(memory_dir):
            src = os.path.join(memory_dir, f)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(claude_dir, f))
        logger.info(
            "Injected %d memory files for user %s", len(os.listdir(memory_dir)), user_id
        )

    # Create CLAUDE.md
    claude_md = os.path.join(workspace, "CLAUDE.md")
    with open(claude_md, "w") as f:
        f.write("# Loop Engineering Agent\n\n")
        f.write("You are an autonomous coding agent running in an isolated sandbox.\n")
        f.write(
            "Git credentials are pre-configured. Clone, commit, and push directly.\n"
        )
        f.write("Always run tests before pushing. Follow the user's coding style.\n")
        f.write(f"User: {user_id}\n")
        if repo_url:
            f.write(f"\nRepository: {repo_url}\n")
            if repo_branch:
                f.write(f"Base branch: {repo_branch}\n")
            if feature_branch:
                f.write(f"Feature branch: {feature_branch}\n")
                f.write(
                    f"\nIMPORTANT: Create and work on branch '{feature_branch}' from '{repo_branch}'.\n"
                )
                f.write(f"Push to '{feature_branch}' when done.\n")

    # Create persistent container
    config = ClaudeCodeConfig(
        enabled=True,
        runner="podman",
        image="claude-sandbox:v2.1.224",
        timeout_seconds=600,
    )
    runner = PodmanClaudeCodeRunner(config)
    container_name = await runner.create_session(
        session_id,
        workspace,
        repo_url=repo_url,
        repo_branch=repo_branch,
        feature_branch=feature_branch,
    )

    logger.info(
        "Sandbox created: container=%s, workspace=%s, repo=%s branch=%s",
        container_name,
        workspace,
        repo_url,
        repo_branch,
    )

    return {
        "container_name": container_name,
        "workspace": workspace,
        "session_id": session_id,
    }


@activity.defn
async def execute_in_sandbox_activity(args: dict[str, Any]) -> dict[str, Any]:
    """Execute a task in an EXISTING sandbox container."""
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    container_name = args["container_name"]
    prompt = args["prompt"]
    task_type = args.get("task_type", "implementation")
    permission_mode = args.get("permission_mode", "acceptEdits")

    logger.info(
        "Executing in sandbox: container=%s, task_type=%s, permission_mode=%s",
        container_name,
        task_type,
        permission_mode,
    )

    config = ClaudeCodeConfig(
        enabled=True,
        runner="podman",
        image="claude-sandbox:v2.1.224",
        timeout_seconds=600,
    )
    runner = PodmanClaudeCodeRunner(config)

    prompt += "\n\nNote: Git credentials are pre-configured. You can clone, commit, and push directly without any tokens."
    prompt += "\nA CLAUDE.md file exists in /workspace with project instructions. Read it first."

    # Stream Claude Code output to Redis for real-time UI updates
    stream_callback = None
    streaming_enabled = args.get("streaming", True)
    if streaming_enabled:
        import json as _json
        import os

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        session_id = args.get("session_id", container_name)
        user_id = args.get("user_id", "anonymous")

        try:
            import redis.asyncio as aioredis

            stream_redis = aioredis.from_url(redis_url, decode_responses=True)
            channel = f"loop-engineering:notifications:{user_id}"

            async def on_stream_event(event: dict) -> None:
                try:
                    await stream_redis.publish(
                        channel,
                        _json.dumps(
                            {
                                "type": "claude_stream",
                                "workflow_id": session_id,
                                "event": event,
                            }
                        ),
                    )
                except Exception:
                    pass

            stream_callback = on_stream_event
        except Exception as e:
            logger.warning("Failed to set up streaming: %s", e)

    result = await runner.execute_in_session(
        container_name,
        prompt,
        task_type,
        permission_mode=permission_mode,
        on_stream_event=stream_callback,
    )

    # Compute cost using config pricing
    cost = result.compute_cost(config.cost.pricing)
    test_result = result.test_result

    logger.info(
        "Sandbox execution complete: exit_code=%d, test_passed=%s, cost=$%.2f",
        result.exit_code,
        test_result.passed,
        cost,
    )

    return {
        "output": result.output,
        "exit_code": result.exit_code,
        "is_error": result.is_error,
        "test_passed": test_result.passed,
        "test_signal": test_result.signal,
        "cost": cost,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "model": result.model,
    }


@activity.defn
async def hibernate_sandbox_activity(args: dict[str, Any]) -> None:
    """Stop container but keep workspace."""
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    container_name = args["container_name"]

    logger.info("Hibernating sandbox: container=%s", container_name)

    config = ClaudeCodeConfig(
        enabled=True,
        runner="podman",
        image="claude-sandbox:v2.1.224",
        timeout_seconds=600,
    )
    runner = PodmanClaudeCodeRunner(config)
    await runner.stop_session(container_name)

    logger.info("Sandbox hibernated: container=%s", container_name)


@activity.defn
async def destroy_sandbox_activity(args: dict[str, Any]) -> None:
    """Remove container and optionally cleanup workspace."""
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed")

    import os
    import shutil

    container_name = args["container_name"]
    workspace = args.get("workspace", "")
    cleanup_workspace = args.get("cleanup_workspace", False)
    user_id = args.get("user_id", "default")

    logger.info(
        "Destroying sandbox: container=%s, cleanup=%s",
        container_name,
        cleanup_workspace,
    )

    # Remove container
    config = ClaudeCodeConfig(
        enabled=True,
        runner="podman",
        image="claude-sandbox:v2.1.224",
        timeout_seconds=600,
    )
    runner = PodmanClaudeCodeRunner(config)
    await runner.destroy_session(container_name)

    # Extract memories before cleanup
    if workspace and os.path.isdir(workspace):
        sandbox_memory = os.path.join(workspace, ".claude", "memory")
        memory_dir = os.path.expanduser(f"~/.claude-memories/{user_id}")
        if os.path.isdir(sandbox_memory):
            os.makedirs(memory_dir, exist_ok=True)
            for f in os.listdir(sandbox_memory):
                src = os.path.join(sandbox_memory, f)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(memory_dir, f))
            logger.info(
                "Extracted %d memory files from sandbox for user %s",
                len(os.listdir(sandbox_memory)),
                user_id,
            )

    # Cleanup workspace if requested
    if cleanup_workspace and workspace:
        shutil.rmtree(workspace, ignore_errors=True)
        logger.info("Workspace cleaned up: %s", workspace)

    logger.info("Sandbox destroyed: container=%s", container_name)
