"""Tests for Claude Code config models."""

from __future__ import annotations

import pytest


class TestClaudeCodeConfigDefaults:
    def test_defaults(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        cfg = ClaudeCodeConfig()
        assert cfg.enabled is False
        assert cfg.runner == "podman"
        assert cfg.image == "claude-sandbox:v2.1.224"
        assert cfg.timeout_seconds == 300
        assert cfg.max_turns == 50
        assert cfg.max_output_bytes == 2_097_152
        assert cfg.streaming_enabled is True
        assert cfg.max_concurrent_per_org == 3
        assert cfg.queue_timeout_seconds == 30.0

    def test_auth_defaults(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        cfg = ClaudeCodeConfig()
        assert cfg.auth.type == "vertex"
        assert cfg.auth.vertex_project_id == ""

    def test_security_defaults(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        cfg = ClaudeCodeConfig()
        assert cfg.security.read_only_rootfs is True
        assert cfg.security.run_as_non_root is True
        assert cfg.security.run_as_user == 1000
        assert cfg.security.drop_capabilities == ["ALL"]
        assert cfg.security.network_policy == "allow_llm_api"

    def test_cost_defaults(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        cfg = ClaudeCodeConfig()
        assert cfg.cost.max_cost_usd_per_invocation == 5.0
        assert cfg.cost.max_cost_usd_per_loop == 25.0
        assert "claude-opus-4-6" in cfg.cost.pricing

    def test_from_dict(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        cfg = ClaudeCodeConfig.model_validate(
            {
                "enabled": True,
                "runner": "k8s",
                "timeout_seconds": 600,
            }
        )
        assert cfg.enabled is True
        assert cfg.runner == "k8s"
        assert cfg.timeout_seconds == 600


class TestClaudeCodeConfigValidation:
    def test_timeout_min(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        with pytest.raises(Exception):
            ClaudeCodeConfig(timeout_seconds=29)

    def test_timeout_max(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        with pytest.raises(Exception):
            ClaudeCodeConfig(timeout_seconds=1801)

    def test_max_turns_min(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        with pytest.raises(Exception):
            ClaudeCodeConfig(max_turns=4)

    def test_concurrent_limit_min(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        with pytest.raises(Exception):
            ClaudeCodeConfig(max_concurrent_per_org=0)

    def test_network_policy_rejects_allow_internet(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        with pytest.raises(Exception):
            ClaudeCodeConfig.model_validate(
                {
                    "security": {
                        "network_policy": "allow_internet",
                    }
                }
            )

    def test_network_policy_valid_values(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        for val in ("deny", "allow_llm_api"):
            cfg = ClaudeCodeConfig.model_validate(
                {
                    "security": {
                        "network_policy": val,
                    }
                }
            )
            assert cfg.security.network_policy == val

    def test_runner_valid_values(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        for val in ("podman", "k8s"):
            cfg = ClaudeCodeConfig(runner=val)
            assert cfg.runner == val

    def test_runner_invalid(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        with pytest.raises(Exception):
            ClaudeCodeConfig(runner="docker")


class TestModelRoutingConfig:
    def test_defaults(self):
        from deep_agent.src.claude_code.config import ClaudeCodeModelRoutingConfig

        cfg = ClaudeCodeModelRoutingConfig()
        assert cfg.planning == "claude-sonnet-4-5"
        assert cfg.design == "claude-opus-4-6"
        assert cfg.implementation == "claude-opus-4-6"
        assert cfg.test_writing == "claude-sonnet-4-5"
        assert cfg.doc_writing == "claude-sonnet-4-5"
        assert cfg.bug_fix == "claude-opus-4-6"
        assert cfg.refactor == "claude-sonnet-4-5"
        assert cfg.default == "claude-opus-4-6"

    def test_get_model_known_type(self):
        from deep_agent.src.claude_code.config import ClaudeCodeModelRoutingConfig

        cfg = ClaudeCodeModelRoutingConfig()
        assert cfg.get_model("test_writing") == "claude-sonnet-4-5"
        assert cfg.get_model("implementation") == "claude-opus-4-6"

    def test_get_model_unknown_type_returns_default(self):
        from deep_agent.src.claude_code.config import ClaudeCodeModelRoutingConfig

        cfg = ClaudeCodeModelRoutingConfig()
        assert cfg.get_model("unknown_type") == "claude-opus-4-6"

    def test_config_has_model_routing(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        cfg = ClaudeCodeConfig()
        assert cfg.model_routing.default == "claude-opus-4-6"
        assert cfg.model_routing.test_writing == "claude-sonnet-4-5"

    def test_override_model_routing(self):
        from deep_agent.src.claude_code.config import ClaudeCodeConfig

        cfg = ClaudeCodeConfig.model_validate({
            "model_routing": {
                "test_writing": "claude-opus-4-6",
                "default": "claude-sonnet-4-5",
            }
        })
        assert cfg.model_routing.test_writing == "claude-opus-4-6"
        assert cfg.model_routing.default == "claude-sonnet-4-5"


class TestLoopEngineeringConfigDefaults:
    def test_defaults(self):
        from deep_agent.src.claude_code.config import LoopEngineeringConfig

        cfg = LoopEngineeringConfig()
        assert cfg.enabled is False
        assert cfg.max_iterations == 5
        assert cfg.struggle_threshold == 3
        assert cfg.error_context_max_chars == 2000
        assert cfg.max_session_reuse_iterations == 3
        assert cfg.checkpoints["plan_review"] is True
        assert cfg.checkpoints["design_review"] is True
        assert cfg.checkpoints["pre_implement"] is False
        assert cfg.checkpoints["on_struggle"] is True

    def test_max_iterations_validation(self):
        from deep_agent.src.claude_code.config import LoopEngineeringConfig

        with pytest.raises(Exception):
            LoopEngineeringConfig(max_iterations=0)

        with pytest.raises(Exception):
            LoopEngineeringConfig(max_iterations=21)
