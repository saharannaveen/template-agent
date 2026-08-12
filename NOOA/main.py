"""NOOA Template Agent — CLI entry point.

Run interactively:
    cd NOOA && uv run python main.py

Run with a single query:
    cd NOOA && uv run python main.py --query "My height is 5'10 and weight is 180 lbs"

Compare with template-agent:
    # template-agent (LangGraph + Aegra):  make local → chat UI
    # NOOA (Object-Oriented Agents):       uv run python main.py → CLI
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from nooa import TextSkill
from nooa.unifiedllm.registry import get_llm_client

from agents.analyst import BMIAnalyst
from agents.orchestrator import HealthAssistant
from agents.publisher import ReportPublisher


def create_agent(model_name: str | None = None) -> HealthAssistant:
    """Create the full agent hierarchy with skills wired up.

    Architecture (mirrors template-agent):
        HealthAssistant (orchestrator)
        ├── BMIAnalyst (analyst subagent)
        │   └── bmi-report skill
        └── ReportPublisher (publisher subagent)
            └── email-formatter skill
        └── client-intake skill
    """
    model = model_name or os.environ.get("NOOA_MODEL", "vertex_ai/gemini-2.5-pro")
    llm = get_llm_client(model)

    skills_dir = Path(__file__).parent / "skills"

    bmi_skill = None
    if (skills_dir / "bmi-report" / "SKILL.md").exists():
        bmi_skill = TextSkill(path=skills_dir / "bmi-report")

    email_skill = None
    if (skills_dir / "email-formatter" / "SKILL.md").exists():
        email_skill = TextSkill(path=skills_dir / "email-formatter")

    intake_skill = None
    if (skills_dir / "client-intake" / "SKILL.md").exists():
        intake_skill = TextSkill(path=skills_dir / "client-intake")

    analyst = BMIAnalyst(llm=llm)
    if bmi_skill:
        analyst.bmi_report = bmi_skill

    publisher = ReportPublisher(llm=llm)
    if email_skill:
        publisher.email_formatter = email_skill

    orchestrator = HealthAssistant(llm=llm)
    orchestrator.analyst = analyst
    orchestrator.publisher = publisher
    if intake_skill:
        orchestrator.client_intake = intake_skill

    return orchestrator


async def run_interactive(agent: HealthAssistant) -> None:
    """Run the agent in interactive CLI mode."""
    print("\n" + "=" * 60)
    print("  NOOA Health Assistant (Object-Oriented Agents)")
    print("  Type 'quit' to exit, 'help' for usage")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        if user_input.lower() == "help":
            print("\nUsage examples:")
            print("  My height is 175 cm and weight is 70 kg")
            print("  I'm 5'10 and weigh 180 lbs")
            print("  BMI for 180cm 85kg, email to user@example.com")
            print("  What is BMI?\n")
            continue

        print("\nAssistant: ", end="", flush=True)
        try:
            result = await agent.handle(user_input)
            if not isinstance(result, str):
                result = str(result)
            print(result)
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
        print()


async def run_single(agent: HealthAssistant, query: str) -> None:
    """Run a single query and print the result."""
    print(f"\nQuery: {query}")
    print("-" * 40)
    result = await agent.handle(query)
    print(result)


def main():
    parser = argparse.ArgumentParser(description="NOOA Health Assistant")
    parser.add_argument("--query", "-q", help="Single query to run (otherwise interactive)")
    parser.add_argument("--model", "-m", help="LLM model name (default: gemini/gemini-2.5-flash)")
    args = parser.parse_args()

    agent = create_agent(model_name=args.model)

    if args.query:
        asyncio.run(run_single(agent, args.query))
    else:
        asyncio.run(run_interactive(agent))


if __name__ == "__main__":
    main()
