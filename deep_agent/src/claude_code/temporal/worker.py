"""Temporal worker entrypoint for Loop Engineering workflows."""

from __future__ import annotations

import asyncio
import logging
import os

try:
    from temporalio.client import Client
    from temporalio.worker import Worker

    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False

from deep_agent.src.claude_code.temporal.activities import (
    create_sandbox_activity,
    destroy_sandbox_activity,
    estimate_cost_activity,
    execute_in_sandbox_activity,
    hibernate_sandbox_activity,
    notify_user_activity,
    post_result_to_chat_activity,
    run_claude_code_activity,
)
from deep_agent.src.claude_code.temporal.workflows import (
    CodingSessionWorkflow,
    LoopEngineeringWorkflow,
)

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    """
    Start Temporal worker for Loop Engineering workflows.

    Configuration via environment variables:
    - TEMPORAL_HOST: Temporal server host (default: localhost:7233)
    - TEMPORAL_NAMESPACE: Temporal namespace (default: default)
    - TEMPORAL_TASK_QUEUE: Task queue name (default: loop-engineering)
    - TEMPORAL_MAX_CONCURRENT_ACTIVITIES: Max concurrent activities (default: 10)
    - TEMPORAL_MAX_CONCURRENT_WORKFLOWS: Max concurrent workflows (default: 10)
    """
    if not TEMPORAL_AVAILABLE:
        raise RuntimeError("Temporal SDK not installed. Install with: pip install temporalio")

    host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "loop-engineering")
    max_concurrent_activities = int(os.environ.get("TEMPORAL_MAX_CONCURRENT_ACTIVITIES", "10"))
    max_concurrent_workflows = int(os.environ.get("TEMPORAL_MAX_CONCURRENT_WORKFLOWS", "10"))

    logger.info("Connecting to Temporal server at %s (namespace: %s)", host, namespace)

    # Connect to Temporal server
    client = await Client.connect(host, namespace=namespace)

    logger.info("Starting worker on task queue: %s", task_queue)

    # Create worker
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[LoopEngineeringWorkflow, CodingSessionWorkflow],
        activities=[
            estimate_cost_activity,
            run_claude_code_activity,
            create_sandbox_activity,
            execute_in_sandbox_activity,
            hibernate_sandbox_activity,
            destroy_sandbox_activity,
            notify_user_activity,
            post_result_to_chat_activity,
        ],
        max_concurrent_workflow_tasks=max_concurrent_workflows,
        max_concurrent_activities=max_concurrent_activities,
    )

    logger.info("Worker started successfully. Press Ctrl+C to stop.")

    # Run worker until interrupted
    await worker.run()


def main() -> None:
    """Main entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.exception("Worker failed: %s", e)
        raise


if __name__ == "__main__":
    main()
