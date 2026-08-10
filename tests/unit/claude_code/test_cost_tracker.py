"""
Tests for CostTracker.

Test-first implementation following TDD workflow.
"""

import pytest
from deep_agent.src.claude_code.cost_tracker import CostTracker


@pytest.fixture
def tracker():
    """Create a fresh CostTracker instance for each test."""
    pricing = {
        "claude-opus-4-6": {"input_per_mtok": 15.0, "output_per_mtok": 75.0},
        "claude-sonnet-4-5": {"input_per_mtok": 3.0, "output_per_mtok": 15.0},
    }
    return CostTracker(pricing=pricing)


def test_record_iteration(tracker):
    """Test recording a single iteration with token counts."""
    tracker.record_iteration(
        tokens_in=10_000,
        tokens_out=5_000,
        model="claude-opus-4-6",
        status="passed",
        duration_seconds=45.2,
    )

    assert len(tracker.iterations) == 1
    iteration = tracker.iterations[0]
    assert iteration["iteration"] == 1
    assert iteration["tokens_in"] == 10_000
    assert iteration["tokens_out"] == 5_000
    assert iteration["model"] == "claude-opus-4-6"
    assert iteration["status"] == "passed"
    assert iteration["duration_seconds"] == 45.2
    # Cost: (10_000/1_000_000)*15.0 + (5_000/1_000_000)*75.0 = 0.15 + 0.375 = 0.525
    assert abs(iteration["cost_usd"] - 0.525) < 0.001


def test_cumulative_cost(tracker):
    """Test cumulative cost calculation across multiple iterations."""
    tracker.record_iteration(
        tokens_in=10_000, tokens_out=5_000, model="claude-opus-4-6", status="failed"
    )
    tracker.record_iteration(
        tokens_in=15_000, tokens_out=8_000, model="claude-opus-4-6", status="failed"
    )
    tracker.record_iteration(
        tokens_in=12_000, tokens_out=6_000, model="claude-opus-4-6", status="passed"
    )

    assert len(tracker.iterations) == 3
    # Iteration 1: (10_000/1_000_000)*15.0 + (5_000/1_000_000)*75.0 = 0.15 + 0.375 = 0.525
    # Iteration 2: (15_000/1_000_000)*15.0 + (8_000/1_000_000)*75.0 = 0.225 + 0.6 = 0.825
    # Iteration 3: (12_000/1_000_000)*15.0 + (6_000/1_000_000)*75.0 = 0.18 + 0.45 = 0.63
    # Total: 0.525 + 0.825 + 0.63 = 1.98

    assert abs(tracker.iterations[0]["cumulative_cost_usd"] - 0.525) < 0.001
    assert abs(tracker.iterations[1]["cumulative_cost_usd"] - 1.35) < 0.001
    assert abs(tracker.iterations[2]["cumulative_cost_usd"] - 1.98) < 0.001


def test_check_budget_within_limit(tracker):
    """Test budget check when cost is within limit."""
    tracker.record_iteration(
        tokens_in=10_000, tokens_out=5_000, model="claude-opus-4-6", status="passed"
    )

    result = tracker.check_budget(max_cost=5.0)
    assert result["within_budget"] is True
    assert abs(result["current_cost"] - 0.525) < 0.001
    assert result["max_cost"] == 5.0
    assert abs(result["remaining"] - 4.475) < 0.001
    assert abs(result["percent_used"] - 10.5) < 0.1


def test_check_budget_exceeded(tracker):
    """Test budget check when cost exceeds limit."""
    tracker.record_iteration(
        tokens_in=50_000, tokens_out=30_000, model="claude-opus-4-6", status="failed"
    )
    tracker.record_iteration(
        tokens_in=50_000, tokens_out=30_000, model="claude-opus-4-6", status="failed"
    )

    # Each iteration: (50_000/1_000_000)*15.0 + (30_000/1_000_000)*75.0 = 0.75 + 2.25 = 3.0
    # Total: 6.0
    result = tracker.check_budget(max_cost=5.0)
    assert result["within_budget"] is False
    assert abs(result["current_cost"] - 6.0) < 0.001
    assert result["max_cost"] == 5.0
    assert abs(result["remaining"] - (-1.0)) < 0.001
    assert abs(result["percent_used"] - 120.0) < 0.1


def test_get_summary(tracker):
    """Test getting usage summary after multiple iterations."""
    tracker.record_iteration(
        tokens_in=10_000, tokens_out=5_000, model="claude-opus-4-6",
        status="failed", duration_seconds=30.5
    )
    tracker.record_iteration(
        tokens_in=15_000, tokens_out=8_000, model="claude-opus-4-6",
        status="passed", duration_seconds=45.2
    )

    summary = tracker.get_summary()
    assert summary["model"] == "claude-opus-4-6"
    assert summary["total_tokens_in"] == 25_000
    assert summary["total_tokens_out"] == 13_000
    assert abs(summary["total_cost_usd"] - 1.35) < 0.001
    assert abs(summary["duration_seconds"] - 75.7) < 0.001
    assert summary["iterations"] == 2
    assert summary["iterations_passed"] == 1
    assert summary["iterations_failed"] == 1


def test_get_summary_empty(tracker):
    """Test getting summary when no iterations recorded."""
    summary = tracker.get_summary()
    assert summary["model"] == "unknown"
    assert summary["total_tokens_in"] == 0
    assert summary["total_tokens_out"] == 0
    assert summary["total_cost_usd"] == 0.0
    assert summary["duration_seconds"] == 0.0
    assert summary["iterations"] == 0
    assert summary["iterations_passed"] == 0
    assert summary["iterations_failed"] == 0


def test_record_iteration_with_unknown_model(tracker):
    """Test recording iteration with a model not in pricing table."""
    tracker.record_iteration(
        tokens_in=10_000, tokens_out=5_000, model="claude-unknown-99", status="passed"
    )

    # Should use default opus pricing
    iteration = tracker.iterations[0]
    assert abs(iteration["cost_usd"] - 0.525) < 0.001


def test_different_models(tracker):
    """Test tracking costs for different models in same session."""
    tracker.record_iteration(
        tokens_in=10_000, tokens_out=5_000, model="claude-sonnet-4-5", status="passed"
    )
    tracker.record_iteration(
        tokens_in=10_000, tokens_out=5_000, model="claude-opus-4-6", status="passed"
    )

    # Sonnet: (10_000/1_000_000)*3.0 + (5_000/1_000_000)*15.0 = 0.03 + 0.075 = 0.105
    # Opus: (10_000/1_000_000)*15.0 + (5_000/1_000_000)*75.0 = 0.15 + 0.375 = 0.525
    # Total: 0.63

    assert abs(tracker.iterations[0]["cost_usd"] - 0.105) < 0.001
    assert abs(tracker.iterations[1]["cost_usd"] - 0.525) < 0.001
    assert abs(tracker.iterations[1]["cumulative_cost_usd"] - 0.63) < 0.001

    summary = tracker.get_summary()
    # Summary should report the most recent model
    assert summary["model"] == "claude-opus-4-6"
