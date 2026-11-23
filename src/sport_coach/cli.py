"""Interactive console coach built on the ADK Runner.

    export PROVIDER=gemini GEMINI_API_KEY=...
    sport-coach            # or: python -m sport_coach.cli
    sport-coach --trace    # also print tool calls / results (execution events)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from sport_coach.agents.workout_agent import build_workout_agent
from sport_coach.config import ConfigError, load_settings

APP_NAME = "sport_coach"
USER_ID = "local_user"


async def chat(trace: bool) -> None:
    settings = load_settings()
    agent = build_workout_agent(settings)

    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)

    print(f"{settings.app_name} — provider: {settings.provider.name} "
          f"({settings.provider.model}). Type 'exit' to quit.\n")

    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            return

        message = types.Content(role="user", parts=[types.Part(text=text)])
        async for event in runner.run_async(
            user_id=USER_ID, session_id=session.id, new_message=message
        ):
            if trace:
                for call in event.get_function_calls():
                    print(f"  [tool call] {call.name}({dict(call.args or {})})")
                for resp in event.get_function_responses():
                    print(f"  [tool result] {resp.name}: {str(resp.response)[:200]}")
            if event.is_final_response() and event.content and event.content.parts:
                reply = "".join(p.text or "" for p in event.content.parts)
                print(f"\ncoach> {reply}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Sports Coach (console)")
    parser.add_argument("--trace", action="store_true", help="print tool events")
    args = parser.parse_args()
    try:
        asyncio.run(chat(args.trace))
    except ConfigError as exc:
        sys.exit(f"Configuration error: {exc}")


if __name__ == "__main__":
    main()
