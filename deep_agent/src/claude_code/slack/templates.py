"""Block Kit template functions for Slack messages."""

from __future__ import annotations


def checkpoint_blocks(
    workflow_id: str,
    task_name: str,
    phase: str,
    cost: float,
    model: str,
    summary: str,
) -> list[dict]:
    """Build Block Kit blocks for checkpoint notification."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📋 {phase} Required"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Task:*\n{task_name}"},
                {"type": "mrkdwn", "text": f"*Phase:*\n{phase}"},
                {"type": "mrkdwn", "text": f"*Cost so far:*\n${cost:.2f}"},
                {"type": "mrkdwn", "text": f"*Model:*\n{model}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:*\n{summary}"},
        },
        {
            "type": "actions",
            "block_id": "checkpoint_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "style": "primary",
                    "action_id": "approve",
                    "value": workflow_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✏️ Modify"},
                    "action_id": "modify",
                    "value": workflow_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Cancel"},
                    "style": "danger",
                    "action_id": "cancel",
                    "value": workflow_id,
                },
            ],
        },
    ]


def completion_blocks(
    workflow_id: str,
    task_name: str,
    pr_url: str,
    cost: float,
    iterations: int,
    tokens_in: int,
    tokens_out: int,
) -> list[dict]:
    """Build Block Kit blocks for completion notification."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "✅ Task Complete"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Task:*\n{task_name}"},
                {"type": "mrkdwn", "text": f"*PR:*\n<{pr_url}|View PR>"},
                {"type": "mrkdwn", "text": f"*Total Cost:*\n${cost:.2f}"},
                {"type": "mrkdwn", "text": f"*Iterations:*\n{iterations}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"📊 *Usage:* {tokens_in:,} input / {tokens_out:,} output tokens | {iterations} iterations",
            },
        },
    ]


def struggle_blocks(
    workflow_id: str,
    task_name: str,
    iteration: int,
    max_iterations: int,
    cost: float,
    last_error: str,
) -> list[dict]:
    """Build Block Kit blocks for struggle alert."""
    # Truncate error if too long
    error_preview = (
        last_error[:500] + "..." if len(last_error) > 500 else last_error
    )

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "⚠️ Agent Needs Help"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Task:* {task_name}\n*Failed:* {iteration} times (max: {max_iterations})\n*Last error:*\n```{error_preview}```\n*Cost so far:* ${cost:.2f}",
            },
        },
        {
            "type": "input",
            "block_id": "guidance_input",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "guidance_text",
                "multiline": True,
                "placeholder": {
                    "type": "plain_text",
                    "text": "Type guidance for the agent (optional)...",
                },
            },
            "label": {"type": "plain_text", "text": "Your guidance"},
        },
        {
            "type": "actions",
            "block_id": "struggle_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 Continue"},
                    "style": "primary",
                    "action_id": "continue",
                    "value": workflow_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "💬 Send Guidance"},
                    "action_id": "intervene",
                    "value": workflow_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Cancel"},
                    "style": "danger",
                    "action_id": "cancel",
                    "value": workflow_id,
                },
            ],
        },
    ]
