"""
Cost tracking for Claude Code loop engineering executions.

Tracks per-iteration and cumulative costs, emits SSE events for live UI updates.
"""

from typing import Any


class CostTracker:
    """
    Track costs across multiple loop iterations.

    Computes per-iteration cost from token counts and pricing,
    maintains cumulative totals, and provides budget checking.
    """

    def __init__(self, pricing: dict[str, dict[str, float]]):
        """
        Initialize cost tracker.

        Args:
            pricing: Model pricing table, e.g.:
                {
                    "claude-opus-4-6": {"input_per_mtok": 15.0, "output_per_mtok": 75.0},
                    "claude-sonnet-4-5": {"input_per_mtok": 3.0, "output_per_mtok": 15.0},
                }
        """
        self.pricing = pricing
        self.iterations: list[dict[str, Any]] = []

    def record_iteration(
        self,
        tokens_in: int,
        tokens_out: int,
        model: str,
        status: str,
        duration_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """
        Record a single iteration with cost calculation.

        Args:
            tokens_in: Input token count
            tokens_out: Output token count
            model: Model name (e.g., "claude-opus-4-6")
            status: "passed" | "failed"
            duration_seconds: Execution duration

        Returns:
            Iteration record with computed cost
        """
        iteration_num = len(self.iterations) + 1

        # Compute cost for this iteration
        cost_usd = self._compute_cost(tokens_in, tokens_out, model)

        # Compute cumulative cost
        cumulative_cost_usd = sum(it["cost_usd"] for it in self.iterations) + cost_usd

        iteration = {
            "iteration": iteration_num,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "model": model,
            "status": status,
            "cost_usd": cost_usd,
            "cumulative_cost_usd": cumulative_cost_usd,
            "duration_seconds": duration_seconds,
        }

        self.iterations.append(iteration)
        return iteration

    def _compute_cost(self, tokens_in: int, tokens_out: int, model: str) -> float:
        """
        Compute cost for a single iteration.

        Args:
            tokens_in: Input token count
            tokens_out: Output token count
            model: Model name

        Returns:
            Cost in USD
        """
        # Get pricing for model, fallback to opus pricing if unknown
        model_pricing = self.pricing.get(
            model,
            {"input_per_mtok": 15.0, "output_per_mtok": 75.0}
        )

        input_cost = (tokens_in / 1_000_000) * model_pricing.get("input_per_mtok", 15.0)
        output_cost = (tokens_out / 1_000_000) * model_pricing.get("output_per_mtok", 75.0)

        return input_cost + output_cost

    def check_budget(self, max_cost: float) -> dict[str, Any]:
        """
        Check if cumulative cost is within budget.

        Args:
            max_cost: Maximum allowed cost in USD

        Returns:
            Budget check result with:
                - within_budget: bool
                - current_cost: float
                - max_cost: float
                - remaining: float
                - percent_used: float
        """
        current_cost = sum(it["cost_usd"] for it in self.iterations)
        remaining = max_cost - current_cost
        percent_used = (current_cost / max_cost * 100) if max_cost > 0 else 0.0

        return {
            "within_budget": current_cost <= max_cost,
            "current_cost": current_cost,
            "max_cost": max_cost,
            "remaining": remaining,
            "percent_used": percent_used,
        }

    def get_summary(self) -> dict[str, Any]:
        """
        Get usage summary for all iterations.

        Returns:
            Summary with total tokens, cost, duration, iterations
        """
        if not self.iterations:
            return {
                "model": "unknown",
                "total_tokens_in": 0,
                "total_tokens_out": 0,
                "total_cost_usd": 0.0,
                "duration_seconds": 0.0,
                "iterations": 0,
                "iterations_passed": 0,
                "iterations_failed": 0,
            }

        total_tokens_in = sum(it["tokens_in"] for it in self.iterations)
        total_tokens_out = sum(it["tokens_out"] for it in self.iterations)
        total_cost_usd = sum(it["cost_usd"] for it in self.iterations)
        duration_seconds = sum(it["duration_seconds"] for it in self.iterations)
        iterations_passed = sum(1 for it in self.iterations if it["status"] == "passed")
        iterations_failed = sum(1 for it in self.iterations if it["status"] == "failed")

        # Use the most recent model
        model = self.iterations[-1]["model"]

        return {
            "model": model,
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "total_cost_usd": total_cost_usd,
            "duration_seconds": duration_seconds,
            "iterations": len(self.iterations),
            "iterations_passed": iterations_passed,
            "iterations_failed": iterations_failed,
        }
