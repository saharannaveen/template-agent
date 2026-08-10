"""Tests for Slack notifier."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestSlackNotifier:
    @pytest.fixture
    def checkpoint_notification(self):
        from deep_agent.src.claude_code.notifications.models import Notification

        return Notification(
            type="checkpoint",
            workflow_id="wf-123",
            task_name="Build shipping API",
            message="Review plan",
            data={
                "phase": "Design Review",
                "model": "claude-opus-4-6",
                "summary": "Design summary",
            },
            cumulative_cost=1.20,
            actions=["approve", "modify", "cancel"],
        )

    @pytest.fixture
    def completion_notification(self):
        from deep_agent.src.claude_code.notifications.models import Notification

        return Notification(
            type="completion",
            workflow_id="wf-456",
            task_name="Build shipping API",
            message="Task complete",
            data={
                "pr_url": "https://github.com/org/repo/pull/42",
                "iterations": 2,
                "tokens_in": 45000,
                "tokens_out": 12000,
            },
            cumulative_cost=4.20,
        )

    @pytest.fixture
    def struggle_notification(self):
        from deep_agent.src.claude_code.notifications.models import Notification

        return Notification(
            type="struggle",
            workflow_id="wf-789",
            task_name="Build shipping API",
            message="Agent needs help",
            data={
                "iteration": 3,
                "max_iterations": 5,
                "last_error": "AssertionError: expected 200 but got 422",
            },
            cumulative_cost=8.50,
        )

    @pytest.mark.asyncio
    async def test_send_checkpoint_notification(self, checkpoint_notification):
        pytest.importorskip("slack_sdk")
        from deep_agent.src.claude_code.slack.notifier import SlackNotifier

        with patch("deep_agent.src.claude_code.slack.notifier.WebClient") as MockWebClient:
            mock_client = Mock()
            mock_client.chat_postMessage = AsyncMock()
            MockWebClient.return_value = mock_client

            notifier = SlackNotifier(
                bot_token="xoxb-test", default_channel="#test"
            )
            await notifier.send(checkpoint_notification)

            # Verify chat_postMessage was called
            mock_client.chat_postMessage.assert_called_once()
            call_args = mock_client.chat_postMessage.call_args
            assert call_args.kwargs["channel"] == "#test"
            assert "blocks" in call_args.kwargs
            blocks = call_args.kwargs["blocks"]
            assert len(blocks) >= 3  # header, fields, actions

    @pytest.mark.asyncio
    async def test_send_completion_notification(self, completion_notification):
        pytest.importorskip("slack_sdk")
        from deep_agent.src.claude_code.slack.notifier import SlackNotifier

        with patch("deep_agent.src.claude_code.slack.notifier.WebClient") as MockWebClient:
            mock_client = Mock()
            mock_client.chat_postMessage = AsyncMock()
            MockWebClient.return_value = mock_client

            notifier = SlackNotifier(
                bot_token="xoxb-test", default_channel="#test"
            )
            await notifier.send(completion_notification)

            mock_client.chat_postMessage.assert_called_once()
            call_args = mock_client.chat_postMessage.call_args
            blocks = call_args.kwargs["blocks"]
            # Completion has header + fields, no action buttons
            assert len(blocks) >= 2

    @pytest.mark.asyncio
    async def test_send_struggle_notification(self, struggle_notification):
        pytest.importorskip("slack_sdk")
        from deep_agent.src.claude_code.slack.notifier import SlackNotifier

        with patch("deep_agent.src.claude_code.slack.notifier.WebClient") as MockWebClient:
            mock_client = Mock()
            mock_client.chat_postMessage = AsyncMock()
            MockWebClient.return_value = mock_client

            notifier = SlackNotifier(
                bot_token="xoxb-test", default_channel="#test"
            )
            await notifier.send(struggle_notification)

            mock_client.chat_postMessage.assert_called_once()
            call_args = mock_client.chat_postMessage.call_args
            blocks = call_args.kwargs["blocks"]
            # Struggle has header, error, input, actions
            assert len(blocks) >= 3

    @pytest.mark.asyncio
    async def test_handles_missing_slack_sdk_gracefully(
        self, checkpoint_notification, monkeypatch
    ):
        # Simulate slack_sdk not installed
        import sys

        monkeypatch.setitem(sys.modules, "slack_sdk", None)

        # Import should handle ImportError
        from deep_agent.src.claude_code.slack.notifier import SlackNotifier

        notifier = SlackNotifier(
            bot_token="xoxb-test", default_channel="#test"
        )
        # Send should not crash
        await notifier.send(checkpoint_notification)
