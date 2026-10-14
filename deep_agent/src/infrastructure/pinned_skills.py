"""Middleware that injects pinned_skills into subagent state.

When a subagent declares ``pinned_skills`` in its frontmatter, this
middleware sets the ``pinned_skills`` state field before the first model
call. The SkillsMiddleware (from deepagents) then reads it and loads
the skill instructions immediately — no read_file round trip needed.
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware

from deep_agent.utils.pylogger import get_python_logger

logger = get_python_logger()


class PinnedSkillsMiddleware(AgentMiddleware):
    """Injects pinned_skills into subagent state on first run."""

    name = "PinnedSkillsMiddleware"

    def __init__(self, pinned_skills: list[str]) -> None:
        self._pinned = list(pinned_skills)

    def before_agent(
        self, state: dict[str, Any], runtime: Any
    ) -> dict[str, Any] | None:
        if state.get("pinned_skills"):
            return None
        logger.info("Pinning %d skill(s): %s", len(self._pinned), self._pinned)
        return {"pinned_skills": self._pinned}
