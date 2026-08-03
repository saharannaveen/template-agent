"""Unit tests for dynamic subagent (CodeInterpreterMiddleware) configuration."""

import pytest

from deep_agent.src.agent.config.middleware import (
    DynamicSubagentConfig,
    MiddlewareDefaults,
    MiddlewareFileConfig,
    ResolvedMiddlewareConfig,
    resolve_middleware,
)


class TestDynamicSubagentConfig:
    """Test DynamicSubagentConfig model defaults and validation."""

    def test_defaults(self):
        cfg = DynamicSubagentConfig()
        assert cfg.enabled is False
        assert cfg.memory_limit == 64 * 1024 * 1024
        assert cfg.timeout == 5.0
        assert cfg.max_ptc_calls == 256
        assert cfg.tool_name == "eval"
        assert cfg.max_result_chars == 4000
        assert cfg.capture_console is True
        assert cfg.subagents is True
        assert cfg.mode == "thread"
        assert cfg.ptc == []

    def test_custom_values(self):
        cfg = DynamicSubagentConfig(
            enabled=True,
            memory_limit=128 * 1024 * 1024,
            timeout=10.0,
            max_ptc_calls=512,
            tool_name="js_eval",
            max_result_chars=8000,
            capture_console=False,
            subagents=False,
            mode="turn",
            ptc=["glob", "grep"],
        )
        assert cfg.enabled is True
        assert cfg.memory_limit == 128 * 1024 * 1024
        assert cfg.timeout == 10.0
        assert cfg.max_ptc_calls == 512
        assert cfg.tool_name == "js_eval"
        assert cfg.max_result_chars == 8000
        assert cfg.capture_console is False
        assert cfg.subagents is False
        assert cfg.mode == "turn"
        assert cfg.ptc == ["glob", "grep"]

    def test_memory_limit_minimum(self):
        with pytest.raises(Exception):
            DynamicSubagentConfig(memory_limit=100)

    def test_timeout_bounds(self):
        with pytest.raises(Exception):
            DynamicSubagentConfig(timeout=0.5)
        with pytest.raises(Exception):
            DynamicSubagentConfig(timeout=31.0)

    def test_mode_validation(self):
        for mode in ("thread", "turn", "call"):
            cfg = DynamicSubagentConfig(mode=mode)
            assert cfg.mode == mode

    def test_invalid_mode_rejected(self):
        with pytest.raises(Exception):
            DynamicSubagentConfig(mode="invalid")


class TestDynamicSubagentInDefaults:
    """Test DynamicSubagentConfig inside MiddlewareDefaults."""

    def test_defaults_include_dynamic_subagents(self):
        defaults = MiddlewareDefaults()
        assert defaults.dynamic_subagents.enabled is False

    def test_custom_dynamic_subagents_in_defaults(self):
        defaults = MiddlewareDefaults(
            dynamic_subagents=DynamicSubagentConfig(enabled=True, ptc=["glob"])
        )
        assert defaults.dynamic_subagents.enabled is True
        assert defaults.dynamic_subagents.ptc == ["glob"]


class TestDynamicSubagentResolution:
    """Test resolve_middleware() passes through dynamic subagent config."""

    def test_default_resolution(self):
        config = MiddlewareFileConfig()
        resolved = resolve_middleware(config, "some-model")
        assert resolved.dynamic_subagents.enabled is False

    def test_enabled_in_defaults(self):
        config = MiddlewareFileConfig(
            defaults=MiddlewareDefaults(
                dynamic_subagents=DynamicSubagentConfig(
                    enabled=True, ptc=["glob", "grep"]
                )
            )
        )
        resolved = resolve_middleware(config, "some-model")
        assert resolved.dynamic_subagents.enabled is True
        assert resolved.dynamic_subagents.ptc == ["glob", "grep"]

    def test_agent_override(self):
        config = MiddlewareFileConfig()
        overrides = {
            "dynamic_subagents": {
                "enabled": True,
                "timeout": 10.0,
                "mode": "turn",
            }
        }
        resolved = resolve_middleware(config, "some-model", overrides)
        assert resolved.dynamic_subagents.enabled is True
        assert resolved.dynamic_subagents.timeout == 10.0
        assert resolved.dynamic_subagents.mode == "turn"

    def test_agent_override_with_ptc(self):
        config = MiddlewareFileConfig()
        overrides = {
            "dynamic_subagents": {
                "enabled": True,
                "ptc": ["web_search"],
            }
        }
        resolved = resolve_middleware(config, "some-model", overrides)
        assert resolved.dynamic_subagents.ptc == ["web_search"]

    def test_resolved_config_includes_dynamic_subagents(self):
        resolved = ResolvedMiddlewareConfig(
            dynamic_subagents=DynamicSubagentConfig(enabled=True)
        )
        assert resolved.dynamic_subagents.enabled is True
