"""CoachService: the application layer between our interfaces and the harness.

UIs (CLI, Streamlit, later FastAPI) talk only to this module and receive our own
CoachEvent objects. Everything ADK-specific (Runner, sessions, Event, genai
types) stays in here, so the harness can be swapped without touching any UI.
"""

import asyncio
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, Literal

from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from sport_coach.agents.header_mapper import (
    build_header_mapper_agent,
    mapper_input,
    parse_mapper_output,
)
from sport_coach.agents.workout_agent import build_workout_agent
from sport_coach.config import Settings
from sport_coach.usage import UsageRecord, UsageStore, now

APP_NAME = "sport_coach"
MAPPER_USER = "importer"

EventKind = Literal["tool_call", "tool_result", "message"]


@dataclass(frozen=True)
class CoachEvent:
    """Harness-neutral execution event."""

    kind: EventKind
    author: str
    name: str | None = None                          # tool name
    data: dict[str, Any] = field(default_factory=dict)  # tool args / tool result
    text: str | None = None                          # message text
    final: bool = False                              # final answer for this turn


class CoachService:
    def __init__(self, settings: Settings, usage: UsageStore | None = None):
        self.settings = settings
        self._usage = usage  # optional LLM call log (Admin tab)
        self._sessions = InMemorySessionService()
        self._runner = Runner(
            app_name=APP_NAME,
            agent=build_workout_agent(settings),
            session_service=self._sessions,
        )
        self._mapper_runner = Runner(
            app_name=APP_NAME,
            agent=build_header_mapper_agent(settings),
            session_service=self._sessions,
        )

    @property
    def provider_label(self) -> str:
        return f"{self.settings.provider.name} · {self.settings.provider.model}"

    # --- Usage tracking ------------------------------------------------------

    def _record(self, agent: str, **fields: Any) -> None:
        if self._usage is None:
            return
        try:
            self._usage.add(UsageRecord(
                ts=now(), provider=self.settings.provider.name,
                model=self.settings.provider.model, agent=agent, **fields,
            ))
        except Exception:  # never let bookkeeping break a chat or an import
            pass

    async def _tracked(self, agent: str, events: AsyncIterator[Event]) -> AsyncIterator[Event]:
        """Pass ADK events through, logging one usage row per model response.

        Latency is the time since the run started or since the last tool result,
        i.e. how long the model took to answer that step.
        """
        mark = time.perf_counter()
        try:
            async for event in events:
                if event.usage_metadata is not None:
                    u = event.usage_metadata
                    self._record(
                        event.author or agent,
                        input_tokens=u.prompt_token_count or 0,
                        output_tokens=(u.candidates_token_count or 0) + (u.thoughts_token_count or 0),
                        cached_tokens=u.cached_content_token_count or 0,
                        latency_ms=round((time.perf_counter() - mark) * 1000),
                    )
                    mark = time.perf_counter()
                elif event.get_function_responses():
                    mark = time.perf_counter()  # the next model call starts after the tools ran
                yield event
        except Exception as exc:
            self._record(agent, latency_ms=round((time.perf_counter() - mark) * 1000),
                         status="error", error=f"{type(exc).__name__}: {exc}"[:500])
            raise

    async def new_session(self, user_id: str) -> str:
        session = await self._sessions.create_session(app_name=APP_NAME, user_id=user_id)
        return session.id

    async def chat(
        self,
        user_id: str,
        session_id: str,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[CoachEvent]:
        """Send one user message; yield events as the agent works.

        `context` is merged into session state (e.g. {"active_file": ...}) so the
        agent knows what the user is looking at in the UI.
        """
        message = types.Content(role="user", parts=[types.Part(text=text)])
        async for event in self._tracked("workout_agent", self._runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message,
            state_delta=context or None,
        )):
            for call in event.get_function_calls():
                yield CoachEvent("tool_call", event.author, call.name, dict(call.args or {}))
            for resp in event.get_function_responses():
                yield CoachEvent("tool_result", event.author, resp.name, dict(resp.response or {}))
            if event.content and event.content.parts:
                reply = "".join(p.text or "" for p in event.content.parts if not p.thought)
                if reply.strip():
                    yield CoachEvent(
                        "message", event.author, text=reply, final=event.is_final_response()
                    )


    async def map_headers(self, headers: list[str], sample_rows: list[list[str]]) -> dict[str, Any]:
        """One-shot structured call: user headers -> template field mapping."""
        session_id = await self.new_session(MAPPER_USER)
        message = types.Content(role="user", parts=[types.Part(text=mapper_input(headers, sample_rows))])
        final = ""
        async for event in self._tracked("header_mapper", self._mapper_runner.run_async(
            user_id=MAPPER_USER, session_id=session_id, new_message=message
        )):
            if event.is_final_response() and event.content and event.content.parts:
                final = "".join(p.text or "" for p in event.content.parts if not p.thought)
        await self._sessions.delete_session(app_name=APP_NAME, user_id=MAPPER_USER, session_id=session_id)
        return parse_mapper_output(final)


class SyncCoachService:
    """Blocking facade for synchronous UIs such as Streamlit.

    Runs CoachService on one long-lived background event loop, because the
    model clients (google-genai, LiteLLM/httpx) bind connections to the loop
    that created them - a fresh asyncio.run() per message would break them.
    """

    _DONE = object()

    def __init__(self, settings: Settings, usage: UsageStore | None = None):
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="coach-loop").start()
        self._service = self._call(self._create(settings, usage))

    async def _create(self, settings: Settings, usage: UsageStore | None) -> CoachService:
        return CoachService(settings, usage)

    def _call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    @property
    def provider_label(self) -> str:
        return self._service.provider_label

    def new_session(self, user_id: str) -> str:
        return self._call(self._service.new_session(user_id))

    def map_headers(self, headers: list[str], sample_rows: list[list[str]]) -> dict[str, Any]:
        return self._call(self._service.map_headers(headers, sample_rows))

    def chat(
        self, user_id: str, session_id: str, text: str, context: dict[str, Any] | None = None
    ) -> Iterator[CoachEvent]:
        """Yield events as they arrive; re-raises errors from the agent run."""
        q: queue.Queue = queue.Queue()

        async def pump() -> None:
            try:
                async for ev in self._service.chat(user_id, session_id, text, context):
                    q.put(ev)
            except Exception as exc:  # surfaced to the caller below
                q.put(exc)
            finally:
                q.put(self._DONE)

        asyncio.run_coroutine_threadsafe(pump(), self._loop)
        while (item := q.get()) is not self._DONE:
            if isinstance(item, Exception):
                raise item
            yield item
