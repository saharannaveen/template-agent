"""Middleware that emits workflow progress events for dynamic subagent transparency."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

from deep_agent.src.streaming.progress_events import (
    generate_workflow_id,
    workflow_end,
    workflow_start,
)


class WorkflowProgressMiddleware(AgentMiddleware):
    """Emits workflow_start/workflow_end events around eval tool calls."""

    def __init__(self, tool_name: str = "eval") -> None:
        """Initialize with the tool name to wrap (default: eval)."""
        self._tool_name = tool_name

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Any,
    ) -> ToolMessage | Any:
        """Wrap a tool call with workflow start/end progress events."""
        tool_call = request.tool_call
        if tool_call.get("name") != self._tool_name:
            return await handler(request)

        wf_id = generate_workflow_id()
        workflow_start(wf_id)
        try:
            result = await handler(request)
            workflow_end(wf_id)
            return result
        except Exception as exc:
            workflow_end(wf_id, error=str(exc))
            raise
