"""Workflow progress event emission for dynamic subagent transparency.

Emits structured events via LangGraph's stream writer so the UI can
render real-time execution progress in the execution overlay.
"""

from __future__ import annotations

import uuid
from typing import Any

from deep_agent.utils.pylogger import get_python_logger

logger = get_python_logger()


def emit_workflow_progress(event: str, data: dict[str, Any]) -> None:
    """Emit a workflow progress event to the SSE stream."""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer({"type": "workflow_progress", "event": event, "data": data})
    except Exception:
        pass


def workflow_start(workflow_id: str, steps: list[dict[str, str]] | None = None) -> None:
    """Signal that a dynamic subagent workflow has started."""
    emit_workflow_progress(
        "workflow_start",
        {
            "workflow_id": workflow_id,
            "steps": steps or [],
        },
    )


def workflow_end(workflow_id: str, error: str | None = None) -> None:
    """Signal that a dynamic subagent workflow has ended."""
    data: dict[str, Any] = {"workflow_id": workflow_id}
    if error:
        data["error"] = error
    emit_workflow_progress("workflow_end", data)


def generate_workflow_id() -> str:
    """Generate a unique workflow ID."""
    return f"wf-{uuid.uuid4().hex[:8]}"
