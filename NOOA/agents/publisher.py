"""Report Publisher agent — NOOA equivalent of template-agent's publisher subagent.

In template-agent this is defined as publisher.md with tool: send_email and skill: email-formatter.
In NOOA, the email formatting skill becomes a TextSkill, and send_email becomes a method.

NOOA pattern mapping:
  - send_email tool → self.send_email() method (deterministic, simulated)
  - email-formatter skill → TextSkill loaded from skills/email-formatter/
  - publisher.md prompt → class docstring
"""

import re

from nooa import Agent, PredictStrategy, TextSkill, strategy

from .models import EmailResult, HealthReport


class ReportPublisher(Agent):
    """You are a Report Publisher that formats health analysis reports
    and delivers them via email.

    Format reports using proper HTML with clear structure. Include all
    BMI data, health tips, and the medical disclaimer.
    """

    email_formatter: TextSkill | None = None

    def validate_email(self, email: str) -> bool:
        """Validate that an email address has a valid format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))

    @strategy(PredictStrategy())
    async def format_report_html(self, report: HealthReport) -> str:
        """Format the health report as clean HTML email body.

        BMI: {report.bmi_result.bmi}
        Category: {report.bmi_result.category}
        Tips: {report.health_tips}

        Create a well-structured HTML email with:
        - A header with "BMI Health Report"
        - BMI value and category prominently displayed
        - Health tips as a numbered list
        - The disclaimer at the bottom in smaller, italic text
        - Professional styling with inline CSS
        """
        ...

    def send_email(self, recipient: str, subject: str, html_body: str) -> EmailResult:
        """Send an email with the formatted report.

        In production this would call an SMTP service or API.
        For now, simulates sending and prints the email.
        """
        if not self.validate_email(recipient):
            return EmailResult(
                success=False,
                recipient=recipient,
                message=f"Invalid email address: {recipient}",
            )

        print(f"\n{'='*60}")
        print(f"  EMAIL SENT (simulated)")
        print(f"  To: {recipient}")
        print(f"  Subject: {subject}")
        print(f"{'='*60}")
        print(f"  Body preview: {html_body[:200]}...")
        print(f"{'='*60}\n")

        return EmailResult(
            success=True,
            recipient=recipient,
            message=f"Report emailed to {recipient}",
        )

    async def publish(self, report: HealthReport, recipient: str) -> EmailResult:
        """Format and send a health report to the given email address."""
        if not self.validate_email(recipient):
            return EmailResult(
                success=False,
                recipient=recipient,
                message=f"Invalid email address: {recipient}",
            )

        html_body = await self.format_report_html(report)
        subject = f"BMI Health Report — {report.bmi_result.category}"
        return self.send_email(recipient, subject, html_body)
