"""Unit tests for dynamic subagent middleware builder wiring."""

from unittest.mock import MagicMock, patch

import pytest

from deep_agent.src.agent.config.middleware import (
    DynamicSubagentConfig,
    ResolvedMiddlewareConfig,
)
from deep_agent.src.infrastructure.middleware import (
    _build_dynamic_subagents,
    build_middleware_list,
)


class TestBuildDynamicSubagents:
    """Test _build_dynamic_subagents() factory function."""

    def test_returns_middleware_when_available(self):
        config = DynamicSubagentConfig(enabled=True)
        result = _build_dynamic_subagents(config)
        assert result is not None
        assert type(result).__name__ == "CodeInterpreterMiddleware"

    def test_passes_config_values(self):
        config = DynamicSubagentConfig(
            enabled=True,
            memory_limit=32 * 1024 * 1024,
            timeout=3.0,
            tool_name="js",
            mode="turn",
            subagents=False,
            capture_console=False,
            max_result_chars=2000,
            max_ptc_calls=128,
        )
        result = _build_dynamic_subagents(config)
        assert result is not None

    def test_passes_ptc_when_specified(self):
        config = DynamicSubagentConfig(enabled=True, ptc=["glob"])
        result = _build_dynamic_subagents(config)
        assert result is not None

    def test_returns_none_when_import_fails(self):
        config = DynamicSubagentConfig(enabled=True)
        with patch("deep_agent.src.infrastructure.middleware.importlib"):
            with patch.dict("sys.modules", {"langchain_quickjs": None}):
                with patch(
                    "deep_agent.src.infrastructure.middleware._build_dynamic_subagents"
                ) as mock_build:
                    mock_build.return_value = None
                    result = mock_build(config)
        assert result is None


class TestBuildMiddlewareListWithDynamicSubagents:
    """Test that build_middleware_list() includes CodeInterpreterMiddleware."""

    @pytest.fixture(autouse=True)
    def _disable_audit(self):
        with patch(
            "deep_agent.src.audit.config.is_audit_enabled",
            return_value=False,
        ):
            yield

    def test_includes_dynamic_subagents_when_enabled(self):
        resolved = ResolvedMiddlewareConfig(
            summarization_tool_enabled=False,
            dynamic_subagents=DynamicSubagentConfig(enabled=True),
        )
        with patch(
            "deep_agent.src.infrastructure.middleware.settings"
        ) as mock_settings:
            mock_settings.MIDDLEWARE_ENABLED = True
            result = build_middleware_list(resolved)

        type_names = [type(m).__name__ for m in result]
        assert "CodeInterpreterMiddleware" in type_names

    def test_excludes_dynamic_subagents_when_disabled(self):
        resolved = ResolvedMiddlewareConfig(
            summarization_tool_enabled=False,
            dynamic_subagents=DynamicSubagentConfig(enabled=False),
        )
        with patch(
            "deep_agent.src.infrastructure.middleware.settings"
        ) as mock_settings:
            mock_settings.MIDDLEWARE_ENABLED = True
            result = build_middleware_list(resolved)

        type_names = [type(m).__name__ for m in result]
        assert "CodeInterpreterMiddleware" not in type_names

    def test_coexists_with_code_execution(self):
        """Both CodeExecutionMiddleware and CodeInterpreterMiddleware can coexist."""
        mock_code_exec = MagicMock()
        mock_code_exec.__class__.__name__ = "CodeExecutionMiddleware"

        resolved = ResolvedMiddlewareConfig(
            summarization_tool_enabled=False,
            dynamic_subagents=DynamicSubagentConfig(enabled=True),
        )
        with (
            patch("deep_agent.src.infrastructure.middleware.settings") as mock_settings,
            patch(
                "deep_agent.src.infrastructure.middleware._build_code_execution",
                return_value=mock_code_exec,
            ),
        ):
            mock_settings.MIDDLEWARE_ENABLED = True
            resolved.code_execution.enabled = True
            result = build_middleware_list(resolved)

        type_names = [type(m).__name__ for m in result]
        assert "CodeInterpreterMiddleware" in type_names
