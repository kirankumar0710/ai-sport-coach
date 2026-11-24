import pytest

from sport_coach.config import ModelPrice
from sport_coach.pricing import Price, cost_usd, lookup


@pytest.mark.parametrize("provider, model, key", [
    ("gemini", "gemini-3.8-flash", "gemini/gemini-3.8-flash"),   # Gemini API price, not Vertex
    ("anthropic", "claude-sonnet-5-5", "claude-sonnet-5-5"),
    ("openai", "gpt-4.1", "gpt-4.1"),
])
def test_litellm_price_list_covers_configured_models(provider, model, key):
    p = lookup(provider, model, {})
    assert p is not None and p.input_per_mtok > 0 and p.output_per_mtok > 0
    assert p.source == f"LiteLLM price list ({key})"


def test_settings_override_wins():
    p = lookup("gemini", "gemini-3.8-flash", {"gemini-3.8-flash": ModelPrice(1.0, 4.0)})
    assert (p.input_per_mtok, p.output_per_mtok, p.source) == (1.0, 4.0, "settings.toml [pricing]")


def test_unknown_model_has_no_price():
    assert lookup("gemini", "gemini-does-not-exist", {}) is None


def test_cost_with_cached_input_rate():
    p = Price(input_per_mtok=2.0, output_per_mtok=10.0, cached_input_per_mtok=0.5, source="t")
    # 1000 input of which 400 cached, 200 output
    assert cost_usd(p, 1000, 200, 400) == pytest.approx((600 * 2.0 + 400 * 0.5 + 200 * 10.0) / 1e6)


def test_cost_without_cached_rate_charges_full_input():
    p = Price(2.0, 10.0, None, "t")
    assert cost_usd(p, 1000, 200, 400) == pytest.approx((1000 * 2.0 + 200 * 10.0) / 1e6)


def test_price_list_status_and_refresh():
    from sport_coach.pricing import price_list_info, refresh_prices

    info = price_list_info()
    assert info is not None and info.source in ("live", "bundled") and info.loaded_at
    refreshed = refresh_prices()  # tests force the bundled copy (conftest), so no network
    assert refreshed.source == "bundled" and refreshed.note == "LITELLM_LOCAL_MODEL_COST_MAP is set"
    assert lookup("openai", "gpt-4.1", {}) is not None  # prices still available after refresh
