"""Configuration models for Claude Code execution and loop engineering."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClaudeCodeAuthConfig(BaseModel):
    """Authentication configuration for Claude Code."""

    type: Literal["vertex", "api_key", "oauth"] = "vertex"
    vertex_project_id: str = ""


class ClaudeCodeSecurityConfig(BaseModel):
    """Security configuration for Claude Code sandbox."""

    read_only_rootfs: bool = True
    run_as_non_root: bool = True
    run_as_user: int = 1000
    drop_capabilities: list[str] = Field(default_factory=lambda: ["ALL"])
    seccomp_profile: str = "RuntimeDefault"
    network_policy: Literal["deny", "allow_llm_api"] = "allow_llm_api"


class ClaudeCodeGitConfig(BaseModel):
    """Git repository configuration for Claude Code workspace."""

    clone_url: str = ""
    branch: str = ""
    extract_diff_on_complete: bool = True


class ClaudeCodeWorkspaceConfig(BaseModel):
    """Workspace volume configuration for Claude Code."""

    volume_type: Literal["emptyDir", "pvc"] = "emptyDir"
    size_limit: str = "1Gi"
    mount_path: str = "/workspace"
    git: ClaudeCodeGitConfig = Field(default_factory=ClaudeCodeGitConfig)


class ClaudeCodeCostConfig(BaseModel):
    """Cost tracking and limits for Claude Code execution."""

    max_cost_usd_per_invocation: float = Field(default=5.0, ge=0.1, le=100.0)
    max_cost_usd_per_loop: float = Field(default=25.0, ge=1.0, le=500.0)
    pricing: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            },
            "claude-sonnet-4-5": {
                "input_per_mtok": 3.0,
                "output_per_mtok": 15.0,
            },
        }
    )


class ClaudeCodeConfig(BaseModel):
    """Configuration for Claude Code sandbox execution."""

    enabled: bool = False
    runner: Literal["podman", "k8s"] = "podman"
    image: str = "claude-sandbox:v2.1.224"
    timeout_seconds: int = Field(default=300, ge=30, le=1800)
    max_turns: int = Field(default=50, ge=5, le=200)
    max_output_bytes: int = 2_097_152
    streaming_enabled: bool = True
    max_concurrent_per_org: int = Field(default=3, ge=1, le=20)
    queue_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)

    auth: ClaudeCodeAuthConfig = Field(default_factory=ClaudeCodeAuthConfig)
    resource_requests: dict[str, str] = Field(
        default_factory=lambda: {"cpu": "500m", "memory": "512Mi"}
    )
    resource_limits: dict[str, str] = Field(
        default_factory=lambda: {"cpu": "2000m", "memory": "2Gi"}
    )
    security: ClaudeCodeSecurityConfig = Field(default_factory=ClaudeCodeSecurityConfig)
    workspace: ClaudeCodeWorkspaceConfig = Field(
        default_factory=ClaudeCodeWorkspaceConfig
    )
    cost: ClaudeCodeCostConfig = Field(default_factory=ClaudeCodeCostConfig)


class LoopEngineeringConfig(BaseModel):
    """Configuration for loop engineering checkpoints and iteration limits."""

    enabled: bool = False
    max_iterations: int = Field(default=5, ge=1, le=20)
    checkpoints: dict[str, bool] = Field(
        default_factory=lambda: {
            "plan_review": True,
            "design_review": True,
            "pre_implement": False,
            "on_struggle": True,
        }
    )
    struggle_threshold: int = Field(default=3, ge=1, le=10)
    error_context_max_chars: int = Field(default=2000, ge=200, le=10000)
    max_session_reuse_iterations: int = Field(default=3, ge=1, le=10)
