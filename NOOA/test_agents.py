"""Quick test script — validates NOOA agents without LLM calls.

Tests deterministic methods (real bodies) directly. LLM-completed methods
(ellipsis bodies) are tested via main.py with a real model.

Run: cd NOOA && uv run python test_agents.py
"""

import asyncio
import sys
from pathlib import Path

from agents.models import BMIResult, HealthReport, HealthTip


def test_bmi_calculation():
    """Test BMIAnalyst.calculate_bmi — deterministic method with real body."""
    from agents.analyst import BMIAnalyst

    analyst = BMIAnalyst.__new__(BMIAnalyst)

    # Normal BMI
    result = analyst.calculate_bmi(175.0, 70.0)
    assert isinstance(result, BMIResult)
    assert result.bmi == 22.9, f"Expected 22.9, got {result.bmi}"
    assert result.category == "Normal", f"Expected Normal, got {result.category}"

    # Underweight
    result = analyst.calculate_bmi(180.0, 55.0)
    assert result.category == "Underweight", f"Expected Underweight, got {result.category}"

    # Overweight
    result = analyst.calculate_bmi(170.0, 80.0)
    assert result.category == "Overweight", f"Expected Overweight, got {result.category}"

    # Obese
    result = analyst.calculate_bmi(165.0, 100.0)
    assert result.category == "Obese", f"Expected Obese, got {result.category}"

    print("  [PASS] BMIAnalyst.calculate_bmi — all categories correct")


def test_unit_conversion():
    """Test HealthAssistant.convert_units — deterministic method."""
    from agents.orchestrator import HealthAssistant

    orch = HealthAssistant.__new__(HealthAssistant)

    # Imperial to metric
    m = orch.convert_units(height_ft=5, height_in=10, weight_lbs=180)
    assert m.was_converted is True
    assert abs(m.height_cm - 177.8) < 0.1, f"Height: expected ~177.8, got {m.height_cm}"
    assert abs(m.weight_kg - 81.6) < 0.2, f"Weight: expected ~81.6, got {m.weight_kg}"

    # Already metric
    m = orch.convert_units(height_cm=175.0, weight_kg=70.0)
    assert m.was_converted is False
    assert m.height_cm == 175.0
    assert m.weight_kg == 70.0

    print("  [PASS] HealthAssistant.convert_units — imperial and metric")


def test_email_validation():
    """Test ReportPublisher.validate_email — deterministic method."""
    from agents.publisher import ReportPublisher

    pub = ReportPublisher.__new__(ReportPublisher)

    assert pub.validate_email("user@example.com") is True
    assert pub.validate_email("test.name+tag@domain.co.uk") is True
    assert pub.validate_email("invalid") is False
    assert pub.validate_email("@no-local.com") is False
    assert pub.validate_email("no-domain@") is False

    print("  [PASS] ReportPublisher.validate_email — valid and invalid emails")


def test_email_send_simulation():
    """Test ReportPublisher.send_email — deterministic method."""
    from agents.publisher import ReportPublisher

    pub = ReportPublisher.__new__(ReportPublisher)

    bmi = BMIResult(bmi=22.9, category="Normal", height_cm=175.0, weight_kg=70.0)
    report = HealthReport(
        bmi_result=bmi,
        health_tips=[HealthTip(text="Stay active")],
    )

    result = pub.send_email("user@example.com", "Test Report", "<h1>Report</h1>")
    assert result.success is True
    assert result.recipient == "user@example.com"

    result = pub.send_email("invalid-email", "Test", "<h1>Nope</h1>")
    assert result.success is False

    print("  [PASS] ReportPublisher.send_email — success and failure paths")


def test_skills_loadable():
    """Test that TextSkill can load all skill directories."""
    from nooa import TextSkill

    skills_dir = Path(__file__).parent / "skills"
    for skill_name in ["bmi-report", "client-intake", "email-formatter"]:
        skill_path = skills_dir / skill_name
        skill = TextSkill(path=skill_path)
        assert skill.id == skill_name, f"Expected {skill_name}, got {skill.id}"

    print("  [PASS] TextSkill loading — all 3 skills load correctly")


def test_agent_creation():
    """Test that the full agent hierarchy can be instantiated."""
    from agents.analyst import BMIAnalyst
    from agents.orchestrator import HealthAssistant
    from agents.publisher import ReportPublisher
    from nooa.unifiedllm.fake import FakeLLMClient

    llm = FakeLLMClient()

    analyst = BMIAnalyst(llm=llm)
    publisher = ReportPublisher(llm=llm)
    orchestrator = HealthAssistant(llm=llm)
    orchestrator.analyst = analyst
    orchestrator.publisher = publisher

    assert orchestrator.analyst is analyst
    assert orchestrator.publisher is publisher

    print("  [PASS] Agent hierarchy — orchestrator → analyst + publisher")


def main():
    print("\n" + "=" * 60)
    print("  NOOA Template Agent — Unit Tests")
    print("  (deterministic methods only, no LLM calls)")
    print("=" * 60 + "\n")

    tests = [
        test_bmi_calculation,
        test_unit_conversion,
        test_email_validation,
        test_email_send_simulation,
        test_skills_loadable,
        test_agent_creation,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'='*60}\n")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
