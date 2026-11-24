"""Workout Agent: analyses workout history with deterministic tools."""

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from sport_coach.config import Settings
from sport_coach.llm.factory import build_generation_config, build_model
from sport_coach.tools.workout_tools import make_workout_tools

INSTRUCTION = """\
You are the Workout Agent of an AI running coach.

How to work:
- Use the tools for every number you report. Never estimate or invent statistics.
- If the user does not name a file and none is selected, call list_workout_files
  first. If there is exactly one file, use it; otherwise ask which one.
- For trend or consistency questions, call weekly_trends as well as summarize_workouts.
- Files differ in what they record. summarize_workouts lists `available_metrics` and
  `not_available`. Only discuss metrics that are available; if the user asks about one
  that isn't (e.g. heart rate), say their file doesn't include it.

How to answer:
- Start with a 2-3 sentence overview, then key metrics, then observations
  (consistency, pace trend, long-run progression, week-over-week volume jumps).
- Flag weekly volume increases above ~10% as a possible injury risk (needs distance data).
- Keep advice general and encouraging. You are not a medical professional;
  suggest seeing one for pain or injury.
"""


def _instruction(ctx: ReadonlyContext) -> str:
    """Context engineering: add what the UI tells us about the user's view."""
    active = ctx.state.get("active_file")
    if not active:
        return INSTRUCTION
    return (
        INSTRUCTION
        + f"\nThe user currently has '{active}' selected in the app. Use it unless"
        " they name another file.\n"
    )


def build_workout_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="workout_agent",
        description="Analyses workout data: pace, distance, frequency and trends.",
        model=build_model(settings.provider),
        generate_content_config=build_generation_config(settings.provider),
        instruction=_instruction,
        tools=make_workout_tools(settings.data_dir),
    )
