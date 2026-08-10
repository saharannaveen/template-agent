"""Slack notifier for sending Block Kit messages."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deep_agent.src.claude_code.notifications.models import Notification

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Sends Block Kit messages to Slack for checkpoint/completion/struggle alerts."""

    def __init__(self, bot_token: str, default_channel: str):
        self._bot_token = bot_token
        self._default_channel = default_channel
        self._client = None

        # Conditionally import slack_sdk
        try:
            from slack_sdk.web.async_client import WebClient

            self._client = WebClient(token=bot_token)
        except ImportError:
            logger.warning(
                "slack_sdk not installed. Slack notifications will be skipped."
            )

    async def send(self, notification: Notification) -> None:
        """Send notification to Slack using Block Kit."""
        if self._client is None:
            logger.warning("Slack client not initialized, skipping notification")
            return

        try:
            blocks = self._build_blocks(notification)
            await self._client.chat_postMessage(
                channel=self._default_channel,
                text=notification.message,  # Fallback text
                blocks=blocks,
            )
            logger.info(
                f"Slack notification sent: {notification.type} for {notification.workflow_id}"
            )
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            raise

    def _build_blocks(self, notification: Notification) -> list[dict]:
        """Build Block Kit blocks based on notification type."""
        from deep_agent.src.claude_code.slack.templates import (
            checkpoint_blocks,
            completion_blocks,
            struggle_blocks,
        )

        if notification.type == "checkpoint":
            return checkpoint_blocks(
                workflow_id=notification.workflow_id,
                task_name=notification.task_name,
                phase=notification.data.get("phase", "Review"),
                cost=notification.cumulative_cost,
                model=notification.data.get("model", "claude-opus-4-6"),
                summary=notification.data.get("summary", notification.message),
            )
        elif notification.type == "completion":
            return completion_blocks(
                workflow_id=notification.workflow_id,
                task_name=notification.task_name,
                pr_url=notification.data.get("pr_url", ""),
                cost=notification.cumulative_cost,
                iterations=notification.data.get("iterations", 1),
                tokens_in=notification.data.get("tokens_in", 0),
                tokens_out=notification.data.get("tokens_out", 0),
            )
        elif notification.type == "struggle":
            return struggle_blocks(
                workflow_id=notification.workflow_id,
                task_name=notification.task_name,
                iteration=notification.data.get("iteration", 0),
                max_iterations=notification.data.get("max_iterations", 5),
                cost=notification.cumulative_cost,
                last_error=notification.data.get("last_error", "Unknown error"),
            )
        else:
            # Fallback for unknown types
            return [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{notification.type.title()}*\n{notification.message}",
                    },
                }
            ]
