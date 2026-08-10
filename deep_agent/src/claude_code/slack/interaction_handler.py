"""Slack interaction handler for button clicks and modals."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def verify_slack_signature(request: Any, signing_secret: str) -> None:
    """Verify Slack request signature to ensure authenticity.

    Args:
        request: FastAPI Request object with headers and body
        signing_secret: Slack app signing secret

    Raises:
        ValueError: If signature verification fails
    """
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    # Check timestamp to prevent replay attacks
    if abs(time.time() - int(timestamp)) > 60 * 5:
        raise ValueError("Request timestamp is too old")

    # Compute expected signature
    sig_basestring = f"v0:{timestamp}:{request.body.decode('utf-8')}"
    expected_signature = (
        "v0="
        + hmac.new(
            signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(expected_signature, signature):
        raise ValueError("Invalid Slack signature")


async def handle_slack_interaction(payload: dict) -> dict:
    """Handle Slack interaction payload (button clicks, modal submissions).

    Args:
        payload: Slack interaction payload

    Returns:
        Response dict with status
    """
    action = payload["actions"][0]
    workflow_id = action["value"]
    action_id = action["action_id"]
    user = payload["user"]["username"]

    # Handle modify action - open modal
    if action_id == "modify":
        await open_modify_modal(
            trigger_id=payload.get("trigger_id", ""),
            workflow_id=workflow_id,
        )
        return {"status": "ok"}

    # Handle intervene action - extract guidance text
    if action_id == "intervene":
        guidance = extract_input_value(payload, "guidance_input", "guidance_text")
        await send_temporal_signal(
            workflow_id,
            {
                "action": "intervene",
                "feedback": guidance,
                "channel": "slack",
                "user": user,
            },
        )
    else:
        # Simple actions (approve, continue, cancel)
        await send_temporal_signal(
            workflow_id,
            {
                "action": action_id,
                "channel": "slack",
                "user": user,
            },
        )

    # Update Slack message to show decision was made
    await update_slack_message(
        channel=payload["channel"]["id"],
        ts=payload["message"]["ts"],
        user=user,
        action=action_id,
    )

    return {"status": "ok"}


def extract_input_value(payload: dict, block_id: str, action_id: str) -> str:
    """Extract text input value from Slack state."""
    try:
        state = payload.get("state", {}).get("values", {})
        block_values = state.get(block_id, {})
        input_data = block_values.get(action_id, {})
        return input_data.get("value", "")
    except (KeyError, TypeError):
        return ""


async def send_temporal_signal(workflow_id: str, response: dict) -> None:
    """Send user response as Temporal Signal (placeholder).

    Args:
        workflow_id: Temporal workflow ID
        response: User response data
    """
    # TODO: Implement Temporal client integration
    logger.info(
        f"Would send Temporal signal to {workflow_id}: {response}"
    )


async def open_modify_modal(trigger_id: str, workflow_id: str) -> None:
    """Open a modal for user to provide modification feedback (placeholder).

    Args:
        trigger_id: Slack trigger ID for opening modal
        workflow_id: Workflow being modified
    """
    # TODO: Implement Slack modal using slack_sdk
    logger.info(
        f"Would open modify modal for workflow {workflow_id} with trigger {trigger_id}"
    )


async def update_slack_message(
    channel: str,
    ts: str,
    user: str,
    action: str,
) -> None:
    """Update Slack message to show decision was made (placeholder).

    Args:
        channel: Slack channel ID
        ts: Message timestamp
        user: Username who made the decision
        action: Action taken (approve, cancel, etc.)
    """
    # TODO: Implement using slack_sdk WebClient.chat_update
    logger.info(
        f"Would update Slack message in {channel} at {ts}: {action} by {user}"
    )
