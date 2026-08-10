"""HTTP routes for workflow management and user actions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deep_agent.src.claude_code.middleware import get_workflow_store
from deep_agent.src.claude_code.workflow_store import WorkflowStore
from deep_agent.utils.pylogger import get_python_logger

logger = get_python_logger()

workflow_router = APIRouter(tags=["workflows"])


def _get_workflow_store() -> WorkflowStore:
    """Get the shared global workflow store instance from middleware."""
    return get_workflow_store()


async def _authenticated_user_id(request: Request) -> str:
    """Return the SSO sub from the incoming Bearer token."""
    from deep_agent.aegra.auth import (
        DEV_USER_ID,
        ENABLE_AUTH,
        ENVIRONMENT,
        _decode_token,
    )

    # Block auth bypass in production
    if ENVIRONMENT == "production" and not ENABLE_AUTH:
        raise HTTPException(
            status_code=500, detail="Authentication bypass disabled in production"
        )

    if not ENABLE_AUTH:
        logger.warning("Auth bypass active for workflow routes (development mode)")
        return DEV_USER_ID

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    payload = _decode_token(auth_header[7:])
    return str(payload["sub"])


async def _send_workflow_signal(workflow_id: str, response: dict[str, Any]) -> None:
    """Send a signal to a Temporal workflow.

    Args:
        workflow_id: Workflow to signal
        response: User response dict with action, feedback, channel, timestamp

    Raises:
        RuntimeError: If Temporal is not available
    """
    try:
        from temporalio.client import Client

        # Attempt to connect to Temporal
        client = await Client.connect("localhost:7233")

        # Send signal to workflow
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("user_responds", response)

        logger.info(
            "workflow_signal_sent",
            workflow_id=workflow_id,
            action=response.get("action"),
        )
    except ImportError:
        logger.warning(
            "temporal_unavailable_signal_ignored",
            workflow_id=workflow_id,
        )
        raise RuntimeError("Temporal SDK not installed")
    except Exception as exc:
        logger.error(
            "workflow_signal_failed",
            workflow_id=workflow_id,
            error=str(exc),
        )
        raise


class WorkflowActionRequest(BaseModel):
    """Request model for workflow actions."""

    action: Literal["approve", "modify", "cancel", "continue", "intervene"]
    feedback: str | None = Field(default=None, description="Optional user feedback")


@workflow_router.get("/workflows")
async def get_workflows(request: Request) -> dict[str, Any]:
    """List all workflows for the current user.

    Queries Temporal if available, otherwise returns from in-memory store.
    """
    user_id = await _authenticated_user_id(request)
    store = _get_workflow_store()

    # In dev mode, show all workflows (user_id mismatch between anonymous and dev-user)
    from deep_agent.aegra.auth import ENABLE_AUTH
    workflows = await store.get_all(None if not ENABLE_AUTH else user_id)

    logger.info(
        "workflows_listed",
        user_id=user_id,
        count=len(workflows),
        store_instance_id=id(store),
        workflows_storage_id=id(store._local),
    )

    return {"workflows": workflows}


@workflow_router.get("/workflows/{workflow_id}")
async def get_workflow_detail(workflow_id: str, request: Request) -> dict[str, Any]:
    """Get workflow detail including status and history.

    Queries Temporal workflow status if available, otherwise returns from store.
    """
    user_id = await _authenticated_user_id(request)
    store = _get_workflow_store()

    workflow = await store.get(workflow_id)

    if workflow is None:
        logger.warning(
            "workflow_not_found",
            workflow_id=workflow_id,
            user_id=user_id,
            store_instance_id=id(store),
        )
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Verify ownership
    if workflow.get("user_id") != user_id:
        logger.warning(
            "workflow_access_denied",
            workflow_id=workflow_id,
            user_id=user_id,
        )
        raise HTTPException(status_code=404, detail="Workflow not found")

    logger.info(
        "workflow_detail_retrieved",
        workflow_id=workflow_id,
        status=workflow.get("status"),
        store_instance_id=id(store),
    )

    return workflow


@workflow_router.post("/workflows/{workflow_id}/action")
async def workflow_action(
    workflow_id: str, action_request: WorkflowActionRequest, request: Request
) -> dict[str, Any]:
    """Send user action to workflow (approve/modify/cancel/intervene).

    Sends a Temporal signal if available, otherwise updates in-memory store.
    """
    user_id = await _authenticated_user_id(request)
    store = _get_workflow_store()

    # Verify workflow exists
    workflow = await store.get(workflow_id)
    if workflow is None:
        logger.warning(
            "workflow_action_workflow_not_found",
            workflow_id=workflow_id,
            user_id=user_id,
        )
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Verify ownership
    if workflow.get("user_id") != user_id:
        logger.warning(
            "workflow_action_access_denied",
            workflow_id=workflow_id,
            user_id=user_id,
        )
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Build response payload
    response_payload = {
        "action": action_request.action,
        "feedback": action_request.feedback,
        "channel": "ui",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Try to send signal to Temporal workflow
    try:
        await _send_workflow_signal(workflow_id, response_payload)
        logger.info(
            "workflow_action_processed",
            workflow_id=workflow_id,
            action=action_request.action,
        )
    except RuntimeError as exc:
        # Temporal not available - log and continue
        logger.warning(
            "workflow_action_temporal_unavailable",
            workflow_id=workflow_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Workflow signaling unavailable (Temporal not connected)",
        ) from exc

    return {
        "status": "success",
        "action": action_request.action,
        "workflow_id": workflow_id,
    }


class ChatResponseRequest(BaseModel):
    """Request model for chat-based workflow responses."""

    message: str = Field(description="User's message from chat")
    action: Literal["approve", "modify", "cancel", "continue", "intervene"] = Field(
        default="approve", description="Action to take"
    )


@workflow_router.post("/workflows/{workflow_id}/respond")
async def respond_to_workflow(
    workflow_id: str, body: ChatResponseRequest, request: Request
) -> dict[str, Any]:
    """Forward user's chat response to Temporal as a signal.

    This endpoint allows the chat UI to send user messages to a running workflow.
    The workflow can then process the message and continue execution.

    Args:
        workflow_id: Workflow to respond to
        body: User message and action
        request: HTTP request (for auth)

    Returns:
        Status indicating signal was sent
    """
    user_id = await _authenticated_user_id(request)
    store = _get_workflow_store()

    # Verify workflow exists
    workflow = await store.get(workflow_id)
    if workflow is None:
        logger.warning(
            "workflow_respond_not_found",
            workflow_id=workflow_id,
            user_id=user_id,
        )
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Verify ownership
    if workflow.get("user_id") != user_id:
        logger.warning(
            "workflow_respond_access_denied",
            workflow_id=workflow_id,
            user_id=user_id,
        )
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Build signal payload
    signal_payload = {
        "action": body.action,
        "feedback": body.message,
        "channel": "chat",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Send signal to Temporal
    try:
        await _send_workflow_signal(workflow_id, signal_payload)
        logger.info(
            "workflow_chat_response_sent",
            workflow_id=workflow_id,
            action=body.action,
        )
    except RuntimeError as exc:
        logger.warning(
            "workflow_chat_response_temporal_unavailable",
            workflow_id=workflow_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Workflow signaling unavailable (Temporal not connected)",
        ) from exc

    return {
        "status": "signal_sent",
        "workflow_id": workflow_id,
        "action": body.action,
    }
