"""Model prices for cost tracking.

Lookup order for a (provider, model):
  1. [pricing] in settings.toml        - your own override, always wins
  2. LiteLLM's model price list        - community-maintained; LiteLLM downloads the
                                          latest copy when it is first imported and falls
                                          back to the copy bundled with the package offline
  3. none                              - tokens are logged, cost stays empty

Costs are calculated when each call happens and stored with it (sport_coach.usage),
so later price changes never rewrite history.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sport_coach.config import ModelPrice


@dataclass(frozen=True)
class Price:
    input_per_mtok: float               # USD per 1M input tokens
    output_per_mtok: float              # USD per 1M output tokens (incl. thinking)
    cached_input_per_mtok: float | None  # USD per 1M cached input tokens, if the vendor discounts them
    source: str                         # where the price came from, shown in the Admin tab


@lru_cache(maxsize=64)
def _from_litellm(provider: str, model: str) -> Price | None:
    try:
        import litellm  # imported lazily: heavy, and fetches the latest price list
    except ImportError:
        return None
    # Provider-qualified key first: "gemini/<model>" is Gemini API pricing (the bare
    # name can be Vertex AI's); Anthropic/OpenAI models are listed under the bare name.
    for key in (f"{provider}/{model}", model):
        entry = litellm.model_cost.get(key)
        if entry and entry.get("input_cost_per_token") is not None:
            cached = entry.get("cache_read_input_token_cost")
            return Price(
                input_per_mtok=entry["input_cost_per_token"] * 1e6,
                output_per_mtok=(entry.get("output_cost_per_token") or 0) * 1e6,
                cached_input_per_mtok=None if cached is None else cached * 1e6,
                source=f"LiteLLM price list ({key})",
            )
    return None


def lookup(provider: str, model: str, overrides: dict[str, ModelPrice]) -> Price | None:
    if model in overrides:
        p = overrides[model]
        return Price(p.input_per_mtok, p.output_per_mtok, None, "settings.toml [pricing]")
    return _from_litellm(provider, model)


def cost_usd(price: Price, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """Cost of one call. Cached input tokens (part of input_tokens) use the cached rate."""
    cached = min(cached_tokens, input_tokens) if price.cached_input_per_mtok is not None else 0
    return (
        (input_tokens - cached) * price.input_per_mtok
        + cached * (price.cached_input_per_mtok or 0)
        + output_tokens * price.output_per_mtok
    ) / 1e6


# --- Price list status and refresh ------------------------------------------------


@dataclass(frozen=True)
class PriceListInfo:
    source: str                 # "live" (downloaded) or "bundled" (copy shipped with LiteLLM)
    loaded_at: str | None       # ISO timestamp, UTC
    note: str | None = None     # why the bundled copy was used, if it was a fallback


def price_list_info() -> PriceListInfo | None:
    """Where LiteLLM's current price list came from, and when it was loaded."""
    try:
        # importing LiteLLM loads the price list (live download, else bundled copy)
        from litellm.litellm_core_utils.get_model_cost_map import get_model_cost_map_source_info
        info = dict(get_model_cost_map_source_info())
    except Exception:  # older/newer LiteLLM without this helper
        return None
    note = info.get("fallback_reason")
    if info.get("is_env_forced"):
        note = "LITELLM_LOCAL_MODEL_COST_MAP is set"
    return PriceListInfo("live" if info.get("source") == "remote" else "bundled",
                         info.get("loaded_at"), note)


def refresh_prices() -> PriceListInfo | None:
    """Download LiteLLM's latest price list now (bundled copy if offline).

    Only affects prices from now on and calls priced later; costs already stored
    with each call keep the price that applied when the call happened.
    """
    import litellm

    latest = litellm.get_model_cost_map(url=litellm.model_cost_map_url)
    if latest:
        litellm.model_cost.clear()       # update in place: LiteLLM modules hold references
        litellm.model_cost.update(latest)
    _from_litellm.cache_clear()
    return price_list_info()
