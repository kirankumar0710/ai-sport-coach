"""Workout function tools for agents.

Thin wrappers over sport_coach.workouts: the LLM decides *when* to call them;
the numbers are always computed in Python. Errors come back as data
({"status": "error", ...}) so the model can explain them instead of crashing.

Note: no `from __future__ import annotations` here - ADK reads these
signatures to build the tool schema the model sees.
"""

from pathlib import Path

from sport_coach import workouts
from sport_coach.workouts import WorkoutDataError


def make_workout_tools(data_dir: Path) -> list:
    """Bind tools to a data directory."""

    def list_workout_files() -> dict:
        """List the workout CSV files available for analysis."""
        return {"status": "success", "files": workouts.list_files(data_dir)}

    def summarize_workouts(file_name: str) -> dict:
        """Compute overall statistics for a workout CSV file: totals, averages,
        average pace, workouts per week, fastest and longest workouts, heart rate,
        elevation and cadence - whichever the file has. `available_metrics` and
        `not_available` say what the file records.

        Args:
            file_name: Name of the CSV file, e.g. "sample_runs.csv".
        """
        try:
            rows = workouts.load_workouts(data_dir, file_name)
        except WorkoutDataError as exc:
            return {"status": "error", "error": str(exc)}
        return {"status": "success", **workouts.summarize(rows)}

    def weekly_trends(file_name: str) -> dict:
        """Break a workout CSV file down by ISO week: workout count, distance,
        duration, average pace, long run, calories, heart rate, elevation, and
        week-over-week distance change with a warning flag above 10%.
        Values are null when the file has no data for them.

        Args:
            file_name: Name of the CSV file, e.g. "sample_runs.csv".
        """
        try:
            rows = workouts.load_workouts(data_dir, file_name)
        except WorkoutDataError as exc:
            return {"status": "error", "error": str(exc)}
        return {"status": "success", "weeks": workouts.weekly(rows)}

    return [list_workout_files, summarize_workouts, weekly_trends]
