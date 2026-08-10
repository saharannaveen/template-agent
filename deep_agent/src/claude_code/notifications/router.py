"""Multi-channel notification router."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from deep_agent.src.claude_code.notifications.chat_ui import ChatUINotifier

if TYPE_CHECKING:
    from deep_agent.src.claude_code.notifications.models import (
        Notification,
        NotificationConfig,
    )

logger = logging.getLogger(__name__)


class BaseNotifier(ABC):
    """Base class for notification channel implementations."""

    @abstractmethod
    async def send(self, notification: Notification) -> None:
        """Send notification to this channel."""
        pass




class WebhookNotifier(BaseNotifier):
    """POST notifications to a configured webhook URL."""

    def __init__(self, url: str):
        self._url = url

    async def send(self, notification: Notification) -> None:
        """POST notification JSON to webhook URL."""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                await client.post(
                    self._url,
                    json=notification.model_dump(),
                    timeout=10.0,
                )
            logger.info(f"Webhook notification sent to {self._url}")
        except ImportError:
            logger.warning("httpx not installed, webhook notification skipped")
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
            raise


class NotificationRouter:
    """Routes notifications to all configured channels concurrently."""

    def __init__(self, config: NotificationConfig):
        self._config = config
        self.channels: list[BaseNotifier] = []

        # Always enable Chat UI
        if config.channels.chat_ui.enabled:
            self.channels.append(ChatUINotifier(config.channels.chat_ui))

        # Optional: Slack
        if config.channels.slack.enabled and config.channels.slack.bot_token:
            try:
                from deep_agent.src.claude_code.slack.notifier import SlackNotifier

                self.channels.append(
                    SlackNotifier(
                        bot_token=config.channels.slack.bot_token,
                        default_channel=config.channels.slack.default_channel,
                    )
                )
            except ImportError:
                logger.warning("slack_sdk not installed, Slack notifications disabled")

        # Optional: Webhook
        if config.channels.webhook.enabled and config.channels.webhook.url:
            self.channels.append(WebhookNotifier(config.channels.webhook.url))

    async def notify(self, notification: Notification) -> None:
        """Send notification to all channels concurrently."""
        results = await asyncio.gather(
            *[ch.send(notification) for ch in self.channels],
            return_exceptions=True,
        )

        # Log any failures but don't raise
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"Channel {i} ({self.channels[i].__class__.__name__}) failed: {result}"
                )
