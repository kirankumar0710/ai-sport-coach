"""Interactive console coach.

    export PROVIDER=gemini GEMINI_API_KEY=...
    python -m sport_coach.cli
    python -m sport_coach.cli --trace   # also print tool calls / results
"""

import argparse
import asyncio
import sys

from sport_coach.config import ConfigError, load_settings
from sport_coach.service import CoachService

USER_ID = "local_user"


async def chat(trace: bool) -> None:
    settings = load_settings()
    coach = CoachService(settings)
    session_id = await coach.new_session(USER_ID)

    print(f"{settings.app_name} — {coach.provider_label}. Type 'exit' to quit.\n")

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

        async for ev in coach.chat(USER_ID, session_id, text):
            if trace and ev.kind == "tool_call":
                print(f"  [tool call] {ev.name}({ev.data})")
            elif trace and ev.kind == "tool_result":
                print(f"  [tool result] {ev.name}: {str(ev.data)[:200]}")
            elif ev.kind == "message" and ev.final:
                print(f"\ncoach> {ev.text}\n")


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
