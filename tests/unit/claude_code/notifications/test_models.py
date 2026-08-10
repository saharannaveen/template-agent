"""Tests for notification models."""

from __future__ import annotations

import pytest


class TestNotification:
    def test_notification_defaults(self):
        from deep_agent.src.claude_code.notifications.models import Notification

        notification = Notification(
            type="checkpoint",
            workflow_id="wf-123",
            task_name="Build API",
            message="Review plan",
        )
        assert notification.type == "checkpoint"
        assert notification.workflow_id == "wf-123"
        assert notification.task_name == "Build API"
        assert notification.message == "Review plan"
        assert notification.data == {}
        assert notification.cumulative_cost == 0.0
        assert notification.actions == []

    def test_notification_with_data(self):
        from deep_agent.src.claude_code.notifications.models import Notification

        notification = Notification(
            type="completion",
            workflow_id="wf-456",
            task_name="Refactor",
            message="Done",
            data={"pr_url": "https://github.com/org/repo/pull/42", "iterations": 2},
            cumulative_cost=4.20,
            actions=["view_pr"],
        )
        assert notification.data["pr_url"] == "https://github.com/org/repo/pull/42"
        assert notification.cumulative_cost == 4.20
        assert notification.actions == ["view_pr"]

    def test_notification_types(self):
        from deep_agent.src.claude_code.notifications.models import Notification

        # Valid types
        for t in ["checkpoint", "completion", "struggle", "cost_alert"]:
            notification = Notification(
                type=t,
                workflow_id="wf-123",
                task_name="Test",
                message="Test",
            )
            assert notification.type == t

    def test_notification_validation(self):
        from deep_agent.src.claude_code.notifications.models import Notification
        from pydantic import ValidationError

        # Invalid type
        with pytest.raises(ValidationError):
            Notification(
                type="invalid_type",
                workflow_id="wf-123",
                task_name="Test",
                message="Test",
            )


class TestNotificationConfig:
    def test_config_defaults(self):
        from deep_agent.src.claude_code.notifications.models import (
            NotificationConfig,
        )

        config = NotificationConfig()
        assert config.channels.chat_ui.enabled is True
        assert config.channels.slack.enabled is False
        assert config.channels.email.enabled is False
        assert config.channels.webhook.enabled is False

    def test_config_slack_enabled(self):
        from deep_agent.src.claude_code.notifications.models import (
            NotificationConfig,
        )

        config = NotificationConfig(
            channels={
                "chat_ui": {"enabled": True, "redis_url": "redis://localhost"},
                "slack": {
                    "enabled": True,
                    "bot_token": "xoxb-test",
                    "signing_secret": "secret",
                    "default_channel": "#test",
                },
            }
        )
        assert config.channels.slack.enabled is True
        assert config.channels.slack.bot_token == "xoxb-test"
        assert config.channels.slack.default_channel == "#test"

    def test_config_all_channels_enabled(self):
        from deep_agent.src.claude_code.notifications.models import (
            NotificationConfig,
        )

        config = NotificationConfig(
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
        assert config.channels.chat_ui.enabled is True
        assert config.channels.slack.enabled is True
        assert config.channels.email.enabled is True
        assert config.channels.webhook.enabled is True
