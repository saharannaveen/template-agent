"""Cost estimation for Claude Code execution based on prompt complexity."""

from __future__ import annotations

# Complexity tier definitions with estimated token usage
COMPLEXITY_TIERS = {
    "trivial": {
        "input_tokens": 5000,
        "output_tokens": 2000,
        "iterations": 1,
    },
    "simple": {
        "input_tokens": 15000,
        "output_tokens": 5000,
        "iterations": 1,
    },
    "medium": {
        "input_tokens": 40000,
        "output_tokens": 15000,
        "iterations": 2,
    },
    "complex": {
        "input_tokens": 80000,
        "output_tokens": 30000,
        "iterations": 3,
    },
}

# Keyword definitions for complexity classification
_COMPLEX_KEYWORDS = [
    "microservice",
    "full feature",
    "migration",
    "refactor across",
    "multiple components",
    "end-to-end",
]

_MEDIUM_KEYWORDS = [
    "with tests",
    "implement",
    "build",
    "create module",
    "add feature",
    "write tests",
]

_SIMPLE_KEYWORDS = [
    "fix bug",
    "add field",
    "rename",
    "update",
    "small change",
]


def classify_complexity(prompt: str) -> str:
    """
    Classify prompt complexity based on keyword matching.

    Args:
        prompt: The user's task prompt

    Returns:
        Complexity tier: "trivial", "simple", "medium", or "complex"
    """
    prompt_lower = prompt.lower()

    # Check in order of precedence: complex > medium > simple
    for keyword in _COMPLEX_KEYWORDS:
        if keyword in prompt_lower:
            return "complex"

    for keyword in _MEDIUM_KEYWORDS:
        if keyword in prompt_lower:
            return "medium"

    for keyword in _SIMPLE_KEYWORDS:
        if keyword in prompt_lower:
            return "simple"

    # Default to medium complexity
    return "medium"


def estimate_cost(
    prompt: str,
    pricing: dict[str, dict[str, float]],
    max_iterations: int,
) -> dict:
    """
    Estimate cost for Claude Code execution based on prompt complexity.

    Args:
        prompt: The user's task prompt
        pricing: Model pricing dict with format:
            {"model-name": {"input_per_mtok": X, "output_per_mtok": Y}}
        max_iterations: Maximum number of iterations allowed

    Returns:
        Dictionary containing:
            - complexity: The classified complexity tier
            - estimated_cost_low: Low-end cost estimate in USD
            - estimated_cost_high: High-end cost estimate in USD
            - max_possible_cost: Maximum possible cost in USD
    """
    complexity = classify_complexity(prompt)
    tier = COMPLEXITY_TIERS[complexity]

    # Get pricing for first available model, fallback to claude-opus-4-6 rates
    if pricing:
        model_name = next(iter(pricing))
        model_pricing = pricing[model_name]
    else:
        model_pricing = {
            "input_per_mtok": 15.0,
            "output_per_mtok": 75.0,
        }

    input_price_per_mtok = model_pricing["input_per_mtok"]
    output_price_per_mtok = model_pricing["output_per_mtok"]

    # Calculate costs per iteration
    input_cost_per_iter = (tier["input_tokens"] / 1_000_000) * input_price_per_mtok
    output_cost_per_iter = (tier["output_tokens"] / 1_000_000) * output_price_per_mtok
    cost_per_iter = input_cost_per_iter + output_cost_per_iter

    # Estimated costs based on tier's default iterations
    estimated_iters = tier["iterations"]
    estimated_cost_low = cost_per_iter * estimated_iters

    # High estimate assumes 1.5x the default iterations
    estimated_cost_high = cost_per_iter * (estimated_iters * 1.5)

    # Max possible cost uses the configured max_iterations
    max_possible_cost = cost_per_iter * max_iterations

    return {
        "complexity": complexity,
        "estimated_cost_low": estimated_cost_low,
        "estimated_cost_high": estimated_cost_high,
        "max_possible_cost": max_possible_cost,
    }
