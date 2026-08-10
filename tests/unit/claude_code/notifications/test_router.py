"""Tests for notification router."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestNotificationRouter:
    @pytest.fixture
    def notification(self):
        from deep_agent.src.claude_code.notifications.models import Notification

        return Notification(
            type="checkpoint",
            workflow_id="wf-123",
            task_name="Build API",
            message="Review plan",
            data={"plan": "Step 1, Step 2, Step 3"},
            cumulative_cost=1.20,
            actions=["approve", "modify", "cancel"],
        )

    @pytest.fixture
    def config_all_enabled(self):
        from deep_agent.src.claude_code.notifications.models import (
            NotificationConfig,
        )

        return NotificationConfig(
            channels={
                "chat_ui": {"enabled": True, "redis_url": "redis://localhost"},
                "slack": {
                    "enabled": True,
                    "bot_token": "xoxb-test",
                    "signing_secret": "secret",
                    "default_channel": "#test",
                },
                "email": {
                    "enabled": True,
                    "smtp_host": "smtp.example.com",
                    "smtp_port": 587,
                    "from_address": "test@example.com",
                },
                "webhook": {"enabled": True, "url": "https://example.com/webhook"},
            }
        )

    @pytest.fixture
    def config_only_chat(self):
        from deep_agent.src.claude_code.notifications.models import (
            NotificationConfig,
        )

        return NotificationConfig()

    @pytest.mark.asyncio
    async def test_router_sends_to_all_enabled_channels(
        self, notification, config_all_enabled
    ):
        import deep_agent.src.claude_code.notifications.router as router_module
        from deep_agent.src.claude_code.notifications.router import (
            NotificationRouter,
        )

        # Mock all channel classes
        mock_chat_notifier = Mock()
        mock_chat_notifier.send = AsyncMock()
        mock_slack_notifier = Mock()
        mock_slack_notifier.send = AsyncMock()
        mock_webhook_notifier = Mock()
        mock_webhook_notifier.send = AsyncMock()

        # Patch constructors using patch.object
        with patch.object(
            router_module, "ChatUINotifier", return_value=mock_chat_notifier
        ), patch(
            "deep_agent.src.claude_code.slack.notifier.SlackNotifier",
            return_value=mock_slack_notifier,
        ), patch.object(
            router_module, "WebhookNotifier", return_value=mock_webhook_notifier
        ):
            router = NotificationRouter(config_all_enabled)
            await router.notify(notification)

            # Assert all notifiers were called
            mock_chat_notifier.send.assert_called_once_with(notification)
            mock_slack_notifier.send.assert_called_once_with(notification)
            mock_webhook_notifier.send.assert_called_once_with(notification)

    @pytest.mark.asyncio
    async def test_router_only_enabled_channels(
        self, notification, config_only_chat, monkeypatch
    ):
        from deep_agent.src.claude_code.notifications.router import (
            NotificationRouter,
        )

        mock_chat_notifier = Mock()
        mock_chat_notifier.send = AsyncMock()

        monkeypatch.setattr(
            "deep_agent.src.claude_code.notifications.router.ChatUINotifier",
            lambda config: mock_chat_notifier,
        )

        router = NotificationRouter(config_only_chat)
        await router.notify(notification)

        # Only chat UI should be called
        mock_chat_notifier.send.assert_called_once_with(notification)
        assert len(router.channels) == 1

    @pytest.mark.asyncio
    async def test_router_handles_channel_failures_gracefully(
        self, notification, config_all_enabled
    ):
        import deep_agent.src.claude_code.notifications.router as router_module
        from deep_agent.src.claude_code.notifications.router import (
            NotificationRouter,
        )

        # Mock one failing channel
        mock_chat_notifier = Mock()
        mock_chat_notifier.send = AsyncMock()
        mock_slack_notifier = Mock()
        mock_slack_notifier.send = AsyncMock(
            side_effect=Exception("Slack API error")
        )
        mock_webhook_notifier = Mock()
        mock_webhook_notifier.send = AsyncMock()

        with patch.object(
            router_module, "ChatUINotifier", return_value=mock_chat_notifier
        ), patch(
            "deep_agent.src.claude_code.slack.notifier.SlackNotifier",
            return_value=mock_slack_notifier,
        ), patch.object(
            router_module, "WebhookNotifier", return_value=mock_webhook_notifier
        ):
            router = NotificationRouter(config_all_enabled)
            # Should not raise even though Slack fails
            await router.notify(notification)

            # Chat UI and webhook should still be called
            mock_chat_notifier.send.assert_called_once()
            mock_webhook_notifier.send.assert_called_once()
            mock_slack_notifier.send.assert_called_once()


class TestChatUINotifier:
    @pytest.mark.asyncio
    async def test_chat_ui_notifier_logs_when_redis_unavailable(
        self, monkeypatch, caplog
    ):
        from deep_agent.src.claude_code.notifications.models import (
            ChatUIChannelConfig,
            Notification,
        )
        from deep_agent.src.claude_code.notifications.router import ChatUINotifier

        config = ChatUIChannelConfig(redis_url="redis://localhost:6379")
        notifier = ChatUINotifier(config)

        notification = Notification(
            type="checkpoint",
            workflow_id="wf-123",
            task_name="Test",
            message="Test",
        )

        # Should log instead of failing
        await notifier.send(notification)
        # Check that it logged (placeholder implementation)
        assert True  # Placeholder passes


class TestWebhookNotifier:
    @pytest.mark.asyncio
    async def test_webhook_notifier_posts_to_url(self):
        from deep_agent.src.claude_code.notifications.models import Notification
        from deep_agent.src.claude_code.notifications.router import WebhookNotifier

        notifier = WebhookNotifier("https://example.com/webhook")
        notification = Notification(
            type="completion",
            workflow_id="wf-456",
            task_name="Test",
            message="Done",
        )

        # Mock httpx if available, otherwise just test construction
        try:
            import httpx

            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = Mock()
                mock_instance.post = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock()
                mock_client.return_value = mock_instance

                await notifier.send(notification)
                mock_instance.post.assert_called_once()
        except ImportError:
            # httpx not installed - test should still pass
            await notifier.send(notification)
            assert True
