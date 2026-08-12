"""Health Assistant Orchestrator — NOOA equivalent of template-agent's PROMPT.md orchestrator.

In template-agent, the orchestrator is defined in config/agent/PROMPT.md with:
  - model: gemini-2.5-pro
  - tools: [validate_email, queue_task, check_task_status, get_pending_results]
  - skills: [client-intake]
  - Subagent dispatch via task() in eval tool

In NOOA, the orchestrator is a Python class where:
  - Subagents are typed fields (pass-by-reference — the LLM sees them as callable objects)
  - Skills are TextSkill fields (LLM can read via doc(self.skill))
  - Routing logic is in the class docstring (the system prompt)
  - The LLM uses CodeActStrategy to write Python that calls self.analyst.analyze()

NOOA pattern mapping:
  - PROMPT.md system prompt → class docstring
  - eval tool + task() → CodeActStrategy with self.analyst / self.publisher methods
  - validate_email tool → self.validate_email() method (deterministic)
  - client-intake skill → TextSkill loaded from skills/client-intake/
  - Subagent delegation → self.analyst.analyze(), self.publisher.publish()
"""

import re

from nooa import Agent, CodeActStrategy, TextSkill, strategy

from .analyst import BMIAnalyst
from .models import ClientMeasurements, EmailResult, HealthReport
from .publisher import ReportPublisher


class HealthAssistant(Agent):
    """You are a Health Assistant orchestrator for Red Hat employees.

    Today's date is dynamically injected at runtime.

    ## Identity

    You are an ORCHESTRATOR — you plan, delegate, and coordinate. You never
    do the work yourself. You have two specialized subagents:

    - self.analyst: BMI analysis expert (calculate BMI, classify, generate tips)
    - self.publisher: Report formatting and email delivery

    ## Execution Routing

    | User Request | Action |
    |---|---|
    | Health metrics (height, weight, BMI) | Convert units if needed, then call self.analyst.analyze(height_cm, weight_kg) |
    | Health metrics + email | Analyze first, then call self.publisher.publish(report, email) |
    | Out of scope | Decline politely, explain what you can do |

    ## Workflow

    1. Parse the user's request to extract height, weight, and optional email
    2. If imperial units, convert using self.convert_units()
    3. Validate email if provided using self.validate_email()
    4. Delegate BMI analysis to self.analyst.analyze(height_cm, weight_kg)
    5. If email requested, delegate to self.publisher.publish(report, email)
    6. Return the complete report to the user

    ## CRITICAL RULES
    - NEVER calculate BMI yourself — always delegate to self.analyst
    - NEVER format reports yourself — always delegate to self.publisher
    - ALWAYS convert imperial to metric before delegating
    - ALWAYS validate email before delegating to publisher

    ## Out of Scope
    - Diet plans, meal plans, food recommendations
    - Exercise or workout routines
    - Weight history, trends, progress tracking
    - Medical diagnosis or treatment advice

    Politely decline out-of-scope requests and explain what you can do.
    """

    analyst: BMIAnalyst
    publisher: ReportPublisher
    client_intake: TextSkill | None = None

    def validate_email(self, email: str) -> bool:
        """Validate an email address format. Returns True if valid."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))

    def convert_units(
        self,
        height_ft: float | None = None,
        height_in: float | None = None,
        height_cm: float | None = None,
        weight_lbs: float | None = None,
        weight_kg: float | None = None,
    ) -> ClientMeasurements:
        """Convert imperial measurements to metric.

        Accepts height in feet+inches or cm, weight in lbs or kg.
        Returns standardized ClientMeasurements in metric units.
        """
        if height_cm is not None:
            final_height = height_cm
            orig_height = f"{height_cm} cm"
            converted = False
        elif height_ft is not None:
            inches = (height_ft * 12) + (height_in or 0)
            final_height = round(inches * 2.54, 1)
            orig_height = f"{int(height_ft)}'{int(height_in or 0)}\""
            converted = True
        else:
            raise ValueError("Height must be provided in cm or feet+inches")

        if weight_kg is not None:
            final_weight = weight_kg
            orig_weight = f"{weight_kg} kg"
        elif weight_lbs is not None:
            final_weight = round(weight_lbs * 0.453592, 1)
            orig_weight = f"{weight_lbs} lbs"
            converted = True
        else:
            raise ValueError("Weight must be provided in kg or lbs")

        return ClientMeasurements(
            height_cm=final_height,
            weight_kg=final_weight,
            original_height=orig_height,
            original_weight=orig_weight,
            was_converted=converted,
        )

    @strategy(CodeActStrategy())
    async def handle(self, user_message: str) -> str:
        """Handle a user message by routing to the appropriate workflow.

        User message: {user_message}

        Follow these steps:
        1. Parse the message for height, weight, and optional email
        2. If measurements are missing, return a message asking for them
        3. Convert units if imperial (use self.convert_units())
        4. Validate email if provided (use self.validate_email())
        5. Delegate to self.analyst.analyze(height_cm, weight_kg)
        6. If email requested, delegate to self.publisher.publish(report, email)
        7. Format and return the results as a clear markdown report
        """
        ...
