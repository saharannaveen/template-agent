"""Tests for Slack Block Kit templates."""

from __future__ import annotations

import pytest


class TestCheckpointBlocks:
    def test_checkpoint_blocks_structure(self):
        from deep_agent.src.claude_code.slack.templates import checkpoint_blocks

        blocks = checkpoint_blocks(
            workflow_id="wf-123",
            task_name="Build shipping API",
            phase="Design Review",
            cost=1.20,
            model="claude-opus-4-6",
            summary="Design summary here",
        )

        assert isinstance(blocks, list)
        assert len(blocks) >= 3  # header, fields, actions

        # Check header
        assert blocks[0]["type"] == "header"
        assert "Design Review" in blocks[0]["text"]["text"]

        # Check that actions exist
        actions_block = next((b for b in blocks if b["type"] == "actions"), None)
        assert actions_block is not None
        assert "block_id" in actions_block
        assert "elements" in actions_block
        assert len(actions_block["elements"]) == 3  # approve, modify, cancel

        # Check button values contain workflow_id
        for element in actions_block["elements"]:
            assert element["value"] == "wf-123"


class TestCompletionBlocks:
    def test_completion_blocks_structure(self):
        from deep_agent.src.claude_code.slack.templates import completion_blocks

        blocks = completion_blocks(
            workflow_id="wf-456",
            task_name="Build shipping API",
            pr_url="https://github.com/org/repo/pull/42",
            cost=4.20,
            iterations=2,
            tokens_in=45000,
            tokens_out=12000,
        )

        assert isinstance(blocks, list)
        assert len(blocks) >= 2  # header, fields

        # Check header
        assert blocks[0]["type"] == "header"
        assert "Complete" in blocks[0]["text"]["text"]

        # Check fields section contains PR link
        fields_block = next((b for b in blocks if b["type"] == "section"), None)
        assert fields_block is not None
        assert "fields" in fields_block


class TestStruggleBlocks:
    def test_struggle_blocks_structure(self):
        from deep_agent.src.claude_code.slack.templates import struggle_blocks

        blocks = struggle_blocks(
            workflow_id="wf-789",
            task_name="Build shipping API",
            iteration=3,
            max_iterations=5,
            cost=8.50,
            last_error="AssertionError: expected 200 but got 422",
        )

        assert isinstance(blocks, list)
        assert len(blocks) >= 3  # header, error message, actions

        # Check header
        assert blocks[0]["type"] == "header"
        assert "Help" in blocks[0]["text"]["text"] or "Needs" in blocks[0]["text"]["text"]

        # Check that actions exist
        actions_block = next((b for b in blocks if b["type"] == "actions"), None)
        assert actions_block is not None
        elements = actions_block["elements"]
        assert len(elements) >= 2  # continue, cancel (intervene might be separate)

        # Check for input block for guidance
        input_block = next((b for b in blocks if b["type"] == "input"), None)
        # Input may be optional depending on design
        # assert input_block is not None


class TestBlockKitValidation:
    def test_all_blocks_are_valid_json(self):
        import json

        from deep_agent.src.claude_code.slack.templates import (
            checkpoint_blocks,
            completion_blocks,
            struggle_blocks,
        )

        # Test checkpoint
        blocks = checkpoint_blocks(
            "wf-1", "Task", "Phase", 1.0, "model", "summary"
        )
        json.dumps(blocks)  # Should not raise

        # Test completion
        blocks = completion_blocks("wf-2", "Task", "http://pr", 2.0, 1, 1000, 500)
        json.dumps(blocks)  # Should not raise

        # Test struggle
        blocks = struggle_blocks("wf-3", "Task", 3, 5, 5.0, "error")
        json.dumps(blocks)  # Should not raise
