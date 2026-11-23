"""Entry point for `adk web adk_apps` / `adk run adk_apps/sport_coach`."""

from sport_coach.agents.workout_agent import build_workout_agent
from sport_coach.config import load_settings

root_agent = build_workout_agent(load_settings())
