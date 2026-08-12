"""BMI Analyst agent — NOOA equivalent of template-agent's analyst subagent.

In template-agent this is defined as analyst.md with allowed_tools [calculate_bmi, search_web].
In NOOA, tools become methods: deterministic ones have real bodies, LLM-completed ones use `...`.

NOOA pattern mapping:
  - calculate_bmi tool → self.calculate_bmi() method (deterministic, real body)
  - search_web tool → self.search_health_tips() method (LLM-completed, ellipsis body)
  - bmi-report skill → TextSkill loaded from skills/bmi-report/
  - analyst.md prompt → class docstring
"""

from nooa import Agent, PredictStrategy, TextSkill, strategy

from .models import BMIResult, HealthReport, HealthTip


class BMIAnalyst(Agent):
    """You are a BMI Analyst for Red Hat employees.

    Calculate and classify BMI using the provided methods — never compute values
    inline or from internal knowledge. Tone must be encouraging and non-judgmental.
    Never use words like "bad" or "failing."
    """

    bmi_report: TextSkill | None = None

    def calculate_bmi(self, height_cm: float, weight_kg: float) -> BMIResult:
        """Calculate BMI from height in centimeters and weight in kilograms.

        Returns a BMIResult with the calculated BMI value and category.
        """
        height_m = height_cm / 100.0
        bmi = round(weight_kg / (height_m ** 2), 1)

        if bmi < 18.5:
            category = "Underweight"
        elif bmi < 25.0:
            category = "Normal"
        elif bmi < 30.0:
            category = "Overweight"
        else:
            category = "Obese"

        return BMIResult(bmi=bmi, category=category, height_cm=height_cm, weight_kg=weight_kg)

    @strategy(PredictStrategy())
    async def generate_health_tips(self, bmi_result: BMIResult) -> list[HealthTip]:
        """Generate 3 specific, actionable health tips based on the BMI category: {bmi_result.category}.

        BMI value: {bmi_result.bmi}
        Category: {bmi_result.category} ({bmi_result.category_description})

        Each tip must be one concise sentence. Tips must be specific to the
        {bmi_result.category} BMI category. Do not provide generic advice.
        Return exactly 3 tips.
        """
        ...

    @strategy(PredictStrategy())
    async def analyze(self, height_cm: float, weight_kg: float) -> HealthReport:
        """Perform a complete BMI analysis for a client.

        Height: {height_cm} cm
        Weight: {weight_kg} kg

        Steps:
        1. Calculate BMI using self.calculate_bmi(height_cm, weight_kg)
        2. Generate health tips using self.generate_health_tips(bmi_result)
        3. Return a complete HealthReport

        The report must include:
        - BMI value rounded to one decimal place
        - BMI category (Underweight/Normal/Overweight/Obese)
        - 3 category-specific health tips
        - The disclaimer: "This is not medical advice. Consult a healthcare professional."
        """
        ...
