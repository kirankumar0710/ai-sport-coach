"""Coach chat tab. Talks only to SyncCoachService - no ADK imports here."""

import streamlit as st

from sport_coach.service import SyncCoachService

USER_ID = "local_user"
SUGGESTIONS = [
    "Analyse my workouts and summarise how I'm doing.",
    "How consistent have I been week to week?",
    "Is my long run progressing safely?",
]


def _reset() -> None:
    st.session_state.pop("coach_session_id", None)
    st.session_state["coach_messages"] = []


def render(coach: SyncCoachService, active_file: str | None) -> None:
    messages: list[dict] = st.session_state.setdefault("coach_messages", [])
    if "coach_session_id" not in st.session_state:
        st.session_state["coach_session_id"] = coach.new_session(USER_ID)

    top = st.columns([4, 1])
    top[0].caption(f"Model: {coach.provider_label}" + (f" · File: {active_file}" if active_file else ""))
    top[1].button("New conversation", on_click=_reset, width="stretch")

    for m in messages:
        with st.chat_message(m["role"]):
            if m.get("tools"):
                st.caption("Tools used: " + ", ".join(m["tools"]))
            st.markdown(m["text"])

    prompt = st.chat_input("Ask your coach…")
    if not messages and not prompt:
        cols = st.columns(len(SUGGESTIONS))
        for col, text in zip(cols, SUGGESTIONS):
            if col.button(text, width="stretch"):
                prompt = text
    if not prompt:
        return

    messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        tools: list[str] = []
        reply = ""
        status = st.status("Thinking…", expanded=False)
        try:
            for ev in coach.chat(
                USER_ID,
                st.session_state["coach_session_id"],
                prompt,
                context={"active_file": active_file} if active_file else None,
            ):
                if ev.kind == "tool_call":
                    tools.append(ev.name)
                    status.update(label=f"Running {ev.name}…")
                    status.write(f"🔧 `{ev.name}({ev.data})`")
                elif ev.kind == "tool_result":
                    ok = ev.data.get("status") != "error"
                    status.write(f"{'✅' if ok else '❌'} `{ev.name}` returned")
                elif ev.kind == "message" and ev.final:
                    reply = ev.text or ""
        except Exception as exc:  # provider/auth/network errors
            status.update(label="Failed", state="error")
            st.error(f"{type(exc).__name__}: {exc}")
            messages.pop()  # let the user retry the same question
            return

        status.update(label=f"Done · {len(tools)} tool call(s)", state="complete")
        if tools:
            st.caption("Tools used: " + ", ".join(tools))
        st.markdown(reply or "_(no response)_")
        messages.append({"role": "assistant", "text": reply, "tools": tools})
