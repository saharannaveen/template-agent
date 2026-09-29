"""LangChain callback handler for LLM-only time-to-first-token measurement."""

import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler

from deep_agent.aegra.otel import record_llm_first_token
from deep_agent.utils.pylogger import get_python_logger

logger = get_python_logger()


class LLMLatencyCallbackHandler(AsyncCallbackHandler):
    """Measures LLM provider latency until first streamed token.

    Attaches model and provider as OTEL attributes when available.
    Thread-safe: each run_id is tracked independently.
    """

    def __init__(self) -> None:
        """Initialize start time tracking dict."""
        super().__init__()
        self._start_times: dict[UUID, float] = {}

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Record monotonic start time for this LLM run."""
        self._start_times[run_id] = time.monotonic()

    async def on_llm_new_token(
        self,
        token: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Record LLM TTFT on the first token and remove the run entry."""
        start = self._start_times.pop(run_id, None)
        if start is None:
            return
        attrs: dict[str, Any] = {}
        chunk = kwargs.get("chunk")
        if chunk is not None:
            response_metadata = getattr(chunk, "response_metadata", None) or {}
            model_name = response_metadata.get("model_name") or response_metadata.get(
                "model"
            )
            if model_name:
                attrs["model"] = model_name
        record_llm_first_token(start, attributes=attrs if attrs else None)

    async def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Clean up run entry on LLM completion."""
        self._start_times.pop(run_id, None)

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Clean up run entry on LLM error."""
        self._start_times.pop(run_id, None)
