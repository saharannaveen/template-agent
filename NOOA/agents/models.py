"""Typed data models shared across agents.

In NOOA, these are the typed I/O contracts — enforced at method boundaries.
Equivalent to template-agent's implicit JSON structures, but compile-time checkable.
"""

from dataclasses import dataclass, field


@dataclass
class ClientMeasurements:
    """Normalized client measurements in metric units."""
    height_cm: float
    weight_kg: float
    original_height: str = ""
    original_weight: str = ""
    was_converted: bool = False


@dataclass
class BMIResult:
    """Result of a BMI calculation with category classification."""
    bmi: float
    category: str
    height_cm: float
    weight_kg: float

    @property
    def category_description(self) -> str:
        descriptions = {
            "Underweight": "below the healthy weight range",
            "Normal": "within the healthy weight range",
            "Overweight": "above the healthy weight range",
            "Obese": "significantly above the healthy weight range",
        }
        return descriptions.get(self.category, "unknown category")


@dataclass
class HealthTip:
    """A single health tip with its source."""
    text: str
    source: str = ""


@dataclass
class HealthReport:
    """Complete health analysis report — the typed output of the analyst."""
    bmi_result: BMIResult
    health_tips: list[HealthTip] = field(default_factory=list)
    disclaimer: str = "This is not medical advice. Consult a healthcare professional."


@dataclass
class EmailRequest:
    """Request to send a report via email."""
    recipient: str
    subject: str
    report: HealthReport
    format: str = "html"


@dataclass
class EmailResult:
    """Result of an email send operation."""
    success: bool
    recipient: str
    message: str = ""
