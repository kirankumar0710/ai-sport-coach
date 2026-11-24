import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from google.adk.models.lite_llm import LiteLlm

from sport_coach.config import ConfigError, ModelPrice, ProviderConfig, Settings, load_settings
from sport_coach.service import CoachService
from sport_coach.usage import UsageRecord, UsageStore, cost_usd

T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


def rec(**kw):
    base = dict(ts=T0, provider="gemini", model="m", agent="workout_agent", input_tokens=1000, output_tokens=200)
    return UsageRecord(**{**base, **kw})


# --- Store ----------------------------------------------------------------------


def test_store_round_trip_filter_and_clear(tmp_path):
    store = UsageStore(tmp_path / "usage.db")
    store.add(rec())
    store.add(rec(ts=T0 + timedelta(days=2), status="error", error="Timeout"))
    assert [r.status for r in store.records()] == ["ok", "error"]
    assert len(store.records(since=T0 + timedelta(days=1))) == 1
    assert store.records()[0] == rec()
    assert store.clear() == 2 and store.records() == []


def test_cost_needs_a_configured_price():
    pricing = {"m": ModelPrice(input_per_mtok=2.0, output_per_mtok=10.0)}
    assert cost_usd(rec(), pricing) == pytest.approx((1000 * 2 + 200 * 10) / 1e6)
    assert cost_usd(rec(model="other"), pricing) is None


def test_pricing_config(tmp_path):
    p = tmp_path / "s.toml"
    p.write_text('[llm]\ndefault_provider = "gemini"\n[llm.providers.gemini]\nmodel = "g"\n'
                 '[pricing]\n"g" = { input = 0.3, output = 2.5 }\n')
    s = load_settings(p, env={"GEMINI_API_KEY": "k"})
    assert s.pricing == {"g": ModelPrice(0.3, 2.5)}
    p.write_text(p.read_text().replace("output = 2.5", 'output = "cheap"'))
    with pytest.raises(ConfigError, match="needs numeric input and output"):
        load_settings(p, env={"GEMINI_API_KEY": "k"})


# --- Tracking through CoachService (Anthropic via LiteLLM, mocked) -------------------


def service(tmp_path, chat_reply, mapper_reply="{}"):
    settings = Settings(
        app_name="t", data_dir=tmp_path,
        provider=ProviderConfig("anthropic", "claude-sonnet-5-5", "ANTHROPIC_API_KEY", "x"),
        available_providers=("anthropic",), usage_db=tmp_path / "usage.db",
    )
    store = UsageStore(settings.usage_db)
    svc = CoachService(settings, store)
    svc._runner.agent.model = LiteLlm(model="anthropic/claude-sonnet-5-5", api_key="x", mock_response=chat_reply)
    svc._mapper_runner.agent.model = LiteLlm(model="anthropic/claude-sonnet-5-5", api_key="x",
                                             mock_response=mapper_reply)
    return svc, store


def test_chat_and_header_mapping_are_logged(tmp_path):
    reply = json.dumps({"matches": [{"field": "date", "column": "Datum"}], "date_order": "unknown"})
    svc, store = service(tmp_path, "You ran 120 km.", reply)

    async def go():
        sid = await svc.new_session("u")
        [e async for e in svc.chat("u", sid, "How am I doing?")]
        await svc.map_headers(["Datum"], [["01.09.2026"]])
    asyncio.run(go())

    rows = store.records()
    assert [r.agent for r in rows] == ["workout_agent", "header_mapper"]
    assert all(r.provider == "anthropic" and r.model == "claude-sonnet-5-5" for r in rows)
    assert all(r.status == "ok" and r.input_tokens > 0 and r.output_tokens > 0 for r in rows)
    assert all(r.latency_ms >= 0 for r in rows)


def test_failed_call_is_logged_and_reraised(tmp_path):
    svc, store = service(tmp_path, chat_reply="ok")
    svc._runner.agent.model = LiteLlm(model="anthropic/claude-sonnet-5-5", api_key="x",
                                      mock_response=RuntimeError("provider down"))

    async def go():
        sid = await svc.new_session("u")
        [e async for e in svc.chat("u", sid, "hi")]
    with pytest.raises(Exception):
        asyncio.run(go())

    (row,) = store.records()
    assert row.status == "error" and "provider down" in row.error


def test_no_store_means_no_logging(tmp_path):
    svc, _ = service(tmp_path, "ok")
    svc._usage = None

    async def go():
        sid = await svc.new_session("u")
        return [e async for e in svc.chat("u", sid, "hi")]
    assert asyncio.run(go())[-1].text == "ok"
