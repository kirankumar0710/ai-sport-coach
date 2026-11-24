"""SyncCoachService bridges a background event loop to blocking callers."""

import pytest

from sport_coach import service
from sport_coach.service import CoachEvent, SyncCoachService


class FakeCoach:
    provider_label = "fake · model"

    def __init__(self, settings):
        pass

    async def new_session(self, user_id):
        return "s1"

    async def chat(self, user_id, session_id, text, context=None):
        yield CoachEvent("tool_call", "agent", "summarize_workouts", {"file_name": "x.csv"})
        if text == "boom":
            raise RuntimeError("provider down")
        yield CoachEvent("message", "agent", text=f"echo {text} {context}", final=True)


@pytest.fixture
def coach(monkeypatch):
    monkeypatch.setattr(service, "CoachService", FakeCoach)
    return SyncCoachService(settings=None)


def test_streams_events_in_order(coach):
    assert coach.new_session("u") == "s1"
    events = list(coach.chat("u", "s1", "hi", {"active_file": "x.csv"}))
    assert [e.kind for e in events] == ["tool_call", "message"]
    assert events[-1].text == "echo hi {'active_file': 'x.csv'}"


def test_reraises_errors_and_stays_usable(coach):
    with pytest.raises(RuntimeError, match="provider down"):
        list(coach.chat("u", "s1", "boom"))
    assert list(coach.chat("u", "s1", "again"))[-1].final
