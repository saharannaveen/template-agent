"""Notification data models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Notification(BaseModel):
    """A notification to send to users about workflow state changes."""

    type: str
    workflow_id: str
    task_name: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    cumulative_cost: float = 0.0
    actions: list[str] = Field(default_factory=list)


class ChatUIChannelConfig(BaseModel):
    """Chat UI notification channel configuration."""

    enabled: bool = True
    redis_url: str = "redis://localhost:6379"


class SlackChannelConfig(BaseModel):
    """Slack notification channel configuration."""

    enabled: bool = False
    bot_token: str = ""
    signing_secret: str = ""
    default_channel: str = "#loop-engineering"
    mention_user: bool = True


class EmailChannelConfig(BaseModel):
    """Email notification channel configuration."""

    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    from_address: str = ""


class WebhookChannelConfig(BaseModel):
    """Webhook notification channel configuration."""

    enabled: bool = False
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


class NotificationChannelsConfig(BaseModel):
    """Configuration for all notification channels."""

    chat_ui: ChatUIChannelConfig = Field(default_factory=ChatUIChannelConfig)
    slack: SlackChannelConfig = Field(default_factory=SlackChannelConfig)
    email: EmailChannelConfig = Field(default_factory=EmailChannelConfig)
    webhook: WebhookChannelConfig = Field(default_factory=WebhookChannelConfig)


class NotificationConfig(BaseModel):
    """Top-level notification configuration."""

    channels: NotificationChannelsConfig = Field(
        default_factory=NotificationChannelsConfig
    )
