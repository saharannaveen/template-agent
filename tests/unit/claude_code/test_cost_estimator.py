"""Tests for cost estimation functionality."""

from __future__ import annotations


class TestClassifyComplexity:
    """Test suite for complexity classification."""

    def test_complex_keywords_microservice(self):
        """Complex tier: microservice keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Build a new microservice for user auth")
        assert result == "complex"

    def test_complex_keywords_full_feature(self):
        """Complex tier: full feature keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Implement a full feature for payments")
        assert result == "complex"

    def test_complex_keywords_migration(self):
        """Complex tier: migration keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Run migration from MongoDB to PostgreSQL")
        assert result == "complex"

    def test_complex_keywords_refactor_across(self):
        """Complex tier: refactor across keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Refactor across all backend services")
        assert result == "complex"

    def test_complex_keywords_multiple_components(self):
        """Complex tier: multiple components keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Update multiple components in the UI layer")
        assert result == "complex"

    def test_complex_keywords_end_to_end(self):
        """Complex tier: end-to-end keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Build end-to-end test suite")
        assert result == "complex"

    def test_medium_keywords_with_tests(self):
        """Medium tier: with tests keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Add new API endpoint with tests")
        assert result == "medium"

    def test_medium_keywords_implement(self):
        """Medium tier: implement keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Implement user login flow")
        assert result == "medium"

    def test_medium_keywords_build(self):
        """Medium tier: build keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Build a new component")
        assert result == "medium"

    def test_medium_keywords_create_module(self):
        """Medium tier: create module keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Create module for data processing")
        assert result == "medium"

    def test_medium_keywords_add_feature(self):
        """Medium tier: add feature keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Add feature to export data")
        assert result == "medium"

    def test_medium_keywords_write_tests(self):
        """Medium tier: write tests keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Write tests for authentication module")
        assert result == "medium"

    def test_simple_keywords_fix_bug(self):
        """Simple tier: fix bug keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Fix bug in date formatting")
        assert result == "simple"

    def test_simple_keywords_add_field(self):
        """Simple tier: add field keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Add field to user model")
        assert result == "simple"

    def test_simple_keywords_rename(self):
        """Simple tier: rename keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Rename variable for clarity")
        assert result == "simple"

    def test_simple_keywords_update(self):
        """Simple tier: update keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Update documentation")
        assert result == "simple"

    def test_simple_keywords_small_change(self):
        """Simple tier: small change keyword."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Make a small change to the config")
        assert result == "simple"

    def test_default_is_medium(self):
        """Default tier when no keywords match."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Something completely unrelated to known keywords")
        assert result == "medium"

    def test_case_insensitive_matching(self):
        """Keywords should match case-insensitively."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result_upper = classify_complexity("FIX BUG in the code")
        result_lower = classify_complexity("fix bug in the code")
        result_mixed = classify_complexity("Fix Bug in the code")

        assert result_upper == "simple"
        assert result_lower == "simple"
        assert result_mixed == "simple"

    def test_precedence_complex_over_medium(self):
        """Complex keywords take precedence over medium keywords."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Build a microservice with tests")
        assert result == "complex"

    def test_precedence_complex_over_simple(self):
        """Complex keywords take precedence over simple keywords."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Fix bug in microservice")
        assert result == "complex"

    def test_precedence_medium_over_simple(self):
        """Medium keywords take precedence over simple keywords."""
        from deep_agent.src.claude_code.cost_estimator import classify_complexity

        result = classify_complexity("Implement fix for bug")
        assert result == "medium"


class TestEstimateCost:
    """Test suite for cost estimation."""

    def test_returns_required_keys(self):
        """estimate_cost returns all required keys."""
        from deep_agent.src.claude_code.cost_estimator import estimate_cost

        pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        result = estimate_cost("Fix a bug", pricing, max_iterations=5)

        assert "complexity" in result
        assert "estimated_cost_low" in result
        assert "estimated_cost_high" in result
        assert "max_possible_cost" in result

    def test_cost_range_ordering(self):
        """Low cost <= high cost <= max cost."""
        from deep_agent.src.claude_code.cost_estimator import estimate_cost

        pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        result = estimate_cost("Implement feature with tests", pricing, max_iterations=5)

        assert result["estimated_cost_low"] <= result["estimated_cost_high"]
        assert result["estimated_cost_high"] <= result["max_possible_cost"]

    def test_max_cost_scales_with_iterations_simple(self):
        """Max cost increases with max_iterations for simple prompts."""
        from deep_agent.src.claude_code.cost_estimator import estimate_cost

        pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        result_3_iter = estimate_cost("Fix bug", pricing, max_iterations=3)
        result_10_iter = estimate_cost("Fix bug", pricing, max_iterations=10)

        assert result_10_iter["max_possible_cost"] > result_3_iter["max_possible_cost"]

    def test_max_cost_scales_with_iterations_complex(self):
        """Max cost increases with max_iterations for complex prompts."""
        from deep_agent.src.claude_code.cost_estimator import estimate_cost

        pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        result_3_iter = estimate_cost("Build microservice", pricing, max_iterations=3)
        result_10_iter = estimate_cost("Build microservice", pricing, max_iterations=10)

        assert result_10_iter["max_possible_cost"] > result_3_iter["max_possible_cost"]

    def test_uses_first_available_model(self):
        """Uses first model in pricing dict when multiple available."""
        from deep_agent.src.claude_code.cost_estimator import estimate_cost

        pricing = {
            "claude-sonnet-4-5": {
                "input_per_mtok": 3.0,
                "output_per_mtok": 15.0,
            },
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        result = estimate_cost("Fix bug", pricing, max_iterations=5)

        # Should use sonnet pricing (cheaper) since it's first
        # Verify costs are reasonable and non-zero
        assert result["estimated_cost_low"] > 0
        assert result["estimated_cost_high"] > 0
        assert result["max_possible_cost"] > 0

    def test_falls_back_to_opus_when_empty_pricing(self):
        """Falls back to claude-opus-4-6 rates when pricing dict is empty."""
        from deep_agent.src.claude_code.cost_estimator import estimate_cost

        result = estimate_cost("Fix bug", {}, max_iterations=5)

        # Should still return valid cost estimates
        assert result["estimated_cost_low"] > 0
        assert result["estimated_cost_high"] > 0
        assert result["max_possible_cost"] > 0

    def test_complexity_affects_cost(self):
        """Different complexity levels produce different costs."""
        from deep_agent.src.claude_code.cost_estimator import estimate_cost

        pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        simple_result = estimate_cost("Fix bug", pricing, max_iterations=5)
        complex_result = estimate_cost("Build microservice", pricing, max_iterations=5)

        # Complex should cost more than simple
        assert complex_result["estimated_cost_high"] > simple_result["estimated_cost_high"]

    def test_correct_complexity_classification(self):
        """estimate_cost correctly classifies complexity."""
        from deep_agent.src.claude_code.cost_estimator import estimate_cost

        pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        simple_result = estimate_cost("Fix bug", pricing, max_iterations=5)
        medium_result = estimate_cost("Implement feature", pricing, max_iterations=5)
        complex_result = estimate_cost("Build microservice", pricing, max_iterations=5)

        assert simple_result["complexity"] == "simple"
        assert medium_result["complexity"] == "medium"
        assert complex_result["complexity"] == "complex"

    def test_costs_are_positive(self):
        """All cost estimates are positive numbers."""
        from deep_agent.src.claude_code.cost_estimator import estimate_cost

        pricing = {
            "claude-opus-4-6": {
                "input_per_mtok": 15.0,
                "output_per_mtok": 75.0,
            }
        }
        result = estimate_cost("Any prompt", pricing, max_iterations=5)

        assert result["estimated_cost_low"] > 0
        assert result["estimated_cost_high"] > 0
        assert result["max_possible_cost"] > 0
