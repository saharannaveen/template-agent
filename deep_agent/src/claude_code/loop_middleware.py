"""LoopEngineeringMiddleware — wraps claude_code calls with self-correction loops."""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage

from deep_agent.src.claude_code.config import (
    ClaudeCodeCostConfig,
    LoopEngineeringConfig,
)

logger = logging.getLogger(__name__)


def _emit_progress(event_type: str, data: dict[str, Any]) -> None:
    """Emit workflow progress event, silently failing if not available."""
    try:
        from deep_agent.src.streaming.progress_events import emit_workflow_progress

        emit_workflow_progress(event_type, data)
    except Exception as exc:
        logger.debug(f"Failed to emit progress event {event_type}: {exc}")


def _compute_cost(
    input_tokens: int, output_tokens: int, model: str, pricing: dict
) -> float:
    """Compute cost from token counts using pricing config.

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: Model name
        pricing: Dict of model -> {input_per_mtok, output_per_mtok}
                Prices are per MILLION tokens.

    Returns:
        Cost in USD, or 0.0 if model not in pricing dict.
    """
    if model not in pricing:
        return 0.0

    model_pricing = pricing[model]
    input_cost = (input_tokens / 1_000_000) * model_pricing["input_per_mtok"]
    output_cost = (output_tokens / 1_000_000) * model_pricing["output_per_mtok"]

    return input_cost + output_cost


def _check_test_result(
    is_error: bool, exit_code: int, output: str
) -> bool:
    """Check if test result indicates success using three-signal detection.

    Args:
        is_error: Error flag from result
        exit_code: Exit code from result
        output: Output text from result

    Returns:
        True if tests passed, False otherwise
    """
    # Signal 1: is_error field
    if is_error:
        return False

    # Signal 2: exit_code
    if exit_code != 0:
        return False

    # Signal 3: output pattern analysis
    output_lower = output.lower()

    # Failure markers
    fail_markers = ["failed", "failure", "error", "traceback", "assert"]
    has_fail = any(marker in output_lower for marker in fail_markers)

    # Pass markers
    pass_markers = ["passed", "tests pass", "all tests", " ok"]
    has_pass = any(marker in output_lower for marker in pass_markers)

    if has_pass and not has_fail:
        return True
    elif has_fail:
        return False
    else:
        # Neither markers found - assume passed
        return True


class LoopEngineeringMiddleware(AgentMiddleware):
    """Wrap claude_code tool calls with iterative self-correction loops."""

    def __init__(
        self, *, config: LoopEngineeringConfig, cost_config: ClaudeCodeCostConfig
    ) -> None:
        """Initialize middleware with loop engineering configuration."""
        self._config = config
        self._cost_config = cost_config

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Any
    ) -> ModelResponse[Any]:
        """Synchronous model call pass-through."""
        return handler(request)

    async def awrap_model_call(
        self, request: ModelRequest[Any], handler: Any
    ) -> ModelResponse[Any]:
        """Async model call pass-through."""
        return await handler(request)

    def wrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """Synchronous tool call pass-through."""
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Any) -> Any:
        """Intercept claude_code tool calls and run self-correction loop."""
        tool_call = request.tool_call
        if tool_call.get("name") != "claude_code":
            return await handler(request)

        # Extract original args
        args = tool_call.get("args", {})
        original_prompt = args.get("prompt", "")
        tool_call_id = tool_call.get("id", "")

        # Loop state
        cumulative_cost = 0.0
        session_id: str | None = args.get("session_id")
        error_context: str | None = None
        last_result: ToolMessage | None = None

        for iteration in range(1, self._config.max_iterations + 1):
            # Build prompt for this iteration
            if error_context and not session_id:
                # No session: prepend error context to original prompt
                prompt = f"{error_context}\n\n{original_prompt}"
            elif error_context and session_id:
                # Has session: use just error context (session has history)
                prompt = error_context
            else:
                # First iteration or no error context
                prompt = original_prompt

            # Create modified tool call request
            modified_args = {**args, "prompt": prompt, "session_id": session_id}

            modified_tool_call = {**tool_call, "args": modified_args}
            iter_request = ToolCallRequest(
                tool_call=modified_tool_call,
                tool=request.tool,
                state=request.state,
                runtime=request.runtime,
            )

            # Call handler (passes through to ClaudeCodeExecutionMiddleware)
            result = await handler(iter_request)

            # Extract claude_code_result from additional_kwargs
            if not isinstance(result, ToolMessage):
                return result

            claude_code_result = result.additional_kwargs.get("claude_code_result")
            if not claude_code_result:
                return result

            # Extract result fields
            output = claude_code_result.get("output", "")
            result_session_id = claude_code_result.get("session_id", "")
            exit_code = claude_code_result.get("exit_code", 0)
            is_error = claude_code_result.get("is_error", False)
            input_tokens = claude_code_result.get("input_tokens", 0)
            output_tokens = claude_code_result.get("output_tokens", 0)
            model = claude_code_result.get("model", "")

            # Compute iteration cost
            iteration_cost = _compute_cost(
                input_tokens, output_tokens, model, self._cost_config.pricing
            )
            cumulative_cost += iteration_cost

            # Check cost circuit breaker
            if cumulative_cost > self._cost_config.max_cost_usd_per_loop:
                # Abort with cost exceeded message
                abort_msg = (
                    f"Loop aborted: cost limit exceeded (${cumulative_cost:.4f} > "
                    f"${self._cost_config.max_cost_usd_per_loop:.2f}). "
                    f"Last result:\n{output}"
                )
                return ToolMessage(
                    content=abort_msg,
                    tool_call_id=tool_call_id,
                    additional_kwargs=result.additional_kwargs,
                )

            # Check test result
            passed = _check_test_result(is_error, exit_code, output)

            # Emit progress event
            status = "passed" if passed else "failed"
            _emit_progress(
                "loop_iteration",
                {
                    "iteration": iteration,
                    "status": status,
                    "cost": iteration_cost,
                    "cumulative_cost": cumulative_cost,
                },
            )

            # If passed, return result
            if passed:
                return result

            # Failed - prepare for next iteration
            last_result = result

            # Build error_context from last N chars of output
            max_chars = self._config.error_context_max_chars
            error_context = output[-max_chars:] if len(output) > max_chars else output

            # Update session_id from result
            session_id = result_session_id if result_session_id else None

            # Check session reuse cap
            if iteration >= self._config.max_session_reuse_iterations:
                session_id = None

        # Exhausted max_iterations - return last result
        return last_result if last_result else result
