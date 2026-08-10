"""Tests for wiring ClaudeCodeExecutionMiddleware into middleware stack."""

from __future__ import annotations


class TestMiddlewareDefaultsHasClaudeCode:
    """Verify that MiddlewareDefaults has claude_code and loop_engineering fields."""

    def test_has_claude_code_field(self):
        from deep_agent.src.agent.config.middleware import MiddlewareDefaults

        defaults = MiddlewareDefaults()
        assert hasattr(defaults, "claude_code")
        assert defaults.claude_code.enabled is False

    def test_has_loop_engineering_field(self):
        from deep_agent.src.agent.config.middleware import MiddlewareDefaults

        defaults = MiddlewareDefaults()
        assert hasattr(defaults, "loop_engineering")
        assert defaults.loop_engineering.enabled is False


class TestResolvedConfigHasClaudeCode:
    """Verify that ResolvedMiddlewareConfig has claude_code and loop_engineering fields."""

    def test_has_claude_code_field(self):
        from deep_agent.src.agent.config.middleware import ResolvedMiddlewareConfig

        resolved = ResolvedMiddlewareConfig()
        assert hasattr(resolved, "claude_code")
        assert resolved.claude_code.enabled is False

    def test_has_loop_engineering_field(self):
        from deep_agent.src.agent.config.middleware import ResolvedMiddlewareConfig

        resolved = ResolvedMiddlewareConfig()
        assert hasattr(resolved, "loop_engineering")
        assert resolved.loop_engineering.enabled is False


class TestBuildMiddlewareListIncludesClaudeCode:
    """Test that build_middleware_list includes ClaudeCodeExecutionMiddleware when enabled."""

    def test_excludes_when_disabled(self):
        from deep_agent.src.agent.config.middleware import ResolvedMiddlewareConfig
        from deep_agent.src.infrastructure.middleware import build_middleware_list

        resolved = ResolvedMiddlewareConfig()
        # Default is disabled
        assert resolved.claude_code.enabled is False

        middlewares = build_middleware_list(resolved)

        # Should not contain ClaudeCodeExecutionMiddleware
        middleware_types = [type(m).__name__ for m in middlewares]
        assert "ClaudeCodeExecutionMiddleware" not in middleware_types

    def test_includes_when_enabled_with_podman(self):
        from deep_agent.src.agent.config.middleware import ResolvedMiddlewareConfig
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.infrastructure.middleware import build_middleware_list

        # Enable claude_code with podman runner
        config = ClaudeCodeConfig(enabled=True, runner="podman")
        resolved = ResolvedMiddlewareConfig(claude_code=config)
        assert resolved.claude_code.enabled is True

        middlewares = build_middleware_list(resolved)

        # Should contain ClaudeCodeExecutionMiddleware
        middleware_types = [type(m).__name__ for m in middlewares]
        assert "ClaudeCodeExecutionMiddleware" in middleware_types

    def test_includes_when_enabled_with_k8s(self):
        from deep_agent.src.agent.config.middleware import ResolvedMiddlewareConfig
        from deep_agent.src.claude_code.config import ClaudeCodeConfig
        from deep_agent.src.infrastructure.middleware import build_middleware_list

        # Enable claude_code with k8s runner
        config = ClaudeCodeConfig(enabled=True, runner="k8s")
        resolved = ResolvedMiddlewareConfig(claude_code=config)
        assert resolved.claude_code.enabled is True

        middlewares = build_middleware_list(resolved)

        # Should contain ClaudeCodeExecutionMiddleware
        middleware_types = [type(m).__name__ for m in middlewares]
        assert "ClaudeCodeExecutionMiddleware" in middleware_types
