"""Admin tab: provider configuration and LLM usage (calls, tokens, cost, latency).

Reads the usage log written by CoachService (sport_coach.usage). Each call's
cost was calculated when it happened, at the price in effect then (LiteLLM's
price list, or [pricing] in settings.toml, which wins) - see sport_coach.pricing.
"""

from datetime import datetime, time, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from sport_coach import pricing
from sport_coach.config import Settings
from sport_coach.providers import get_provider
from sport_coach.ui.dashboard import inject_panel_css
from sport_coach.usage import UsageRecord, UsageStore

PERIODS = ("Today", "7 days", "30 days", "All time")
_INPUT, _OUTPUT = "#2a78d6", "#eb6834"  # categorical slots 1 and 2 of the reference palette


def _since(period: str) -> datetime | None:
    local_now = datetime.now().astimezone()
    if period == "Today":
        return datetime.combine(local_now.date(), time.min, tzinfo=local_now.tzinfo)
    if period == "7 days":
        return local_now - timedelta(days=7)
    if period == "30 days":
        return local_now - timedelta(days=30)
    return None


def _money(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "–"
    return f"${v:,.4f}" if v < 1 else f"${v:,.2f}"


def _row_cost(rec: UsageRecord, settings: Settings) -> tuple[float | None, str]:
    """Stored cost (priced when the call happened). Calls logged before costs were
    stored are priced now, and labelled so."""
    if rec.cost_usd is not None:
        return rec.cost_usd, rec.price_source or ""
    if rec.status == "ok":
        price = pricing.lookup(rec.provider, rec.model, settings.pricing)
        if price is not None:
            cost = pricing.cost_usd(price, rec.input_tokens, rec.output_tokens, rec.cached_tokens)
            return cost, f"{price.source}, priced later"
    return None, ""


def _price_text(price: pricing.Price | None) -> str:
    if price is None:
        return "unknown: add it under [pricing] in settings.toml"
    cached = f" · cached input {price.cached_input_per_mtok:g}" if price.cached_input_per_mtok is not None else ""
    return f"input {price.input_per_mtok:g} · output {price.output_per_mtok:g}{cached}  ({price.source})"


def _price_list_text() -> str:
    info = pricing.price_list_info()
    if info is None:
        return "price list status unknown"
    when = ""
    if info.loaded_at:
        loaded = datetime.fromisoformat(info.loaded_at).astimezone()
        when = f", loaded {loaded:%d %b %H:%M}"
    if info.source == "live":
        return f"prices: LiteLLM live price list{when}"
    return f"prices: LiteLLM bundled copy{when}" + (f" ({info.note})" if info.note else "")


def _config_table(settings: Settings) -> None:
    cfg = settings.provider
    provider = get_provider(cfg.name)
    price = pricing.lookup(cfg.name, cfg.model, settings.pricing)
    temp = (f"{cfg.temperature} (header mapper: 0)" if provider.allows_temperature(cfg) and cfg.temperature is not None
            else "not sent: model default")
    rows = [
        ("Provider", cfg.name),
        ("Model", cfg.model),
        ("API key", f"{cfg.api_key_env}: {'set' if cfg.api_key else 'not set'}"),
        ("Temperature", temp),
        ("Max output tokens", str(cfg.max_output_tokens or "model default")),
        ("Base URL", cfg.base_url or "vendor default"),
        ("Current price (USD / 1M tokens)", _price_text(price)),
        ("Configured providers", ", ".join(settings.available_providers)),
        ("Usage log", str(settings.usage_db)),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Setting", "Value"]), hide_index=True, width="stretch")
    st.caption("Change with `export PROVIDER=…` / `MODEL=…` or `config/settings.toml`, then restart the app.")


def _clear(store: UsageStore) -> None:
    store.clear()
    st.session_state.pop("admin_confirm_clear", None)


def render(settings: Settings, store: UsageStore) -> None:
    inject_panel_css()

    st.subheader("Configuration")
    _config_table(settings)

    # Heading with a refresh icon at the right end. Every rerun re-reads the log,
    # so clicking it simply reruns the page; the toast and timestamp confirm it.
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.subheader("LLM usage")
        refreshed = st.button("", icon=":material/refresh:", key="admin_refresh",
                              help="Refresh: reload usage from the log and fetch the latest model prices")
    if refreshed:
        # Refresh = re-read the usage log (every rerun does) + download the latest prices.
        with st.spinner("Fetching the latest model prices…"):
            try:
                info = pricing.refresh_prices()
                where = "latest prices" if info and info.source == "live" else "bundled prices (offline)"
                st.toast(f"Usage refreshed · {where}", icon=":material/check_circle:")
            except Exception as exc:  # keep the current list if the download fails
                st.toast(f"Usage refreshed · couldn't update prices ({type(exc).__name__})",
                         icon=":material/warning:")
    st.caption(f"Updated {datetime.now():%H:%M:%S} · {_price_list_text()}")

    period = st.segmented_control("Period", PERIODS, default="7 days", key="admin_period") or "7 days"
    records = store.records(_since(period))
    if not records:
        st.info("No model calls in this period. Usage is recorded for coach chat and for uploads "
                "of new file formats (with an API key).")
        return

    df = pd.DataFrame([r.__dict__ for r in records])
    costs = [_row_cost(r, settings) for r in records]
    df["cost"] = [c for c, _ in costs]
    df["price_source"] = [src for _, src in costs]
    df["local_ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(datetime.now().astimezone().tzinfo)
    ok = df[df["status"] == "ok"]
    priced = df["cost"].notna()

    # --- Headline numbers -----------------------------------------------------
    t = st.columns(6)
    t[0].metric("LLM calls", f"{len(df):,}")
    t[1].metric("Input tokens", f"{int(df['input_tokens'].sum()):,}")
    t[2].metric("Output tokens", f"{int(df['output_tokens'].sum()):,}", help="Includes thinking tokens")
    if priced.any():
        partial = "" if priced.all() else " Excludes calls to models with no known price."
        t[3].metric("Est. cost", _money(df.loc[priced, "cost"].sum()),
                    help="Each call is priced when it happens, at the price in effect then "
                         "(LiteLLM's price list, or [pricing] in settings.toml), and stored. "
                         "Estimate: excludes taxes, discounts and free tiers." + partial)
    else:
        t[3].metric("Est. cost", "–", help="No known price for these models: add them under [pricing] "
                                          "in config/settings.toml.")
    t[4].metric("Avg response", f"{ok['latency_ms'].mean() / 1000:.1f} s" if len(ok) else "–",
                help="Time for the model to answer one step (excludes tool execution)")
    t[5].metric("Errors", f"{(df['status'] == 'error').sum():,}")

    # --- Breakdown by provider / model / agent ----------------------------------
    st.markdown("**By provider, model and agent**")
    by = (
        df.groupby(["provider", "model", "agent"])
        .agg(calls=("status", "size"), input_tokens=("input_tokens", "sum"),
             output_tokens=("output_tokens", "sum"), cost=("cost", lambda c: c.sum(min_count=1)),
             avg_latency_s=("latency_ms", lambda s: round(s.mean() / 1000, 2)),
             errors=("status", lambda s: int((s == "error").sum())))
        .reset_index()
    )
    by["cost"] = by["cost"].map(_money)
    num = st.column_config.NumberColumn
    st.dataframe(by, hide_index=True, width="stretch", column_config={
        "provider": "Provider", "model": "Model", "agent": "Agent",
        "calls": num("Calls", format="localized"),
        "input_tokens": num("Input tokens", format="localized"),
        "output_tokens": num("Output tokens", format="localized"),
        "cost": "Est. cost", "avg_latency_s": num("Avg response (s)", format="%.2f"),
        "errors": num("Errors", format="localized"),
    })

    # --- Daily tokens -------------------------------------------------------------
    daily = (
        df.assign(day=df["local_ts"].dt.tz_localize(None).dt.normalize())
        .groupby("day")[["input_tokens", "output_tokens"]].sum().reset_index()
        .melt("day", var_name="kind", value_name="tokens")
    )
    daily["kind"] = daily["kind"].map({"input_tokens": "Input", "output_tokens": "Output"})
    daily["label"] = daily["day"].dt.strftime("%d %b")  # one discrete bar per day
    days = list(dict.fromkeys(daily.sort_values("day")["label"]))
    with st.container(border=True, key="panel-admin-daily"):
        st.markdown("**Tokens per day**")
        chart = (
            alt.Chart(daily)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=26)
            .encode(
                x=alt.X("label:O", title=None, sort=days, axis=alt.Axis(labelAngle=0, grid=False)),
                y=alt.Y("sum(tokens):Q", title=None),
                color=alt.Color("kind:N", scale=alt.Scale(domain=["Input", "Output"], range=[_INPUT, _OUTPUT]),
                                legend=alt.Legend(title=None, orient="top")),
                order=alt.Order("kind:N"),
                tooltip=[alt.Tooltip("day:T", title="Day", format="%a %d %b"),
                         alt.Tooltip("kind:N", title="Tokens"), alt.Tooltip("tokens:Q", title="Count", format=",")],
            )
            .properties(height=260, background="transparent")
        )
        st.altair_chart(chart, width="stretch")

    # --- Recent calls ---------------------------------------------------------------
    with st.expander(f"Recent calls ({min(len(df), 50)} of {len(df)})"):
        recent = df.sort_values("local_ts", ascending=False).head(50)
        st.dataframe(
            pd.DataFrame({
                "time": recent["local_ts"].dt.strftime("%Y-%m-%d %H:%M:%S"),
                "agent": recent["agent"], "provider": recent["provider"], "model": recent["model"],
                "input tokens": recent["input_tokens"], "output tokens": recent["output_tokens"],
                "latency_s": (recent["latency_ms"] / 1000).round(2),
                "cost": recent["cost"].map(_money), "price source": recent["price_source"],
                "status": recent["status"],
                "error": recent["error"].fillna(""),
            }),
            hide_index=True, width="stretch",
        )

    # --- Maintenance ------------------------------------------------------------------
    if st.session_state.get("admin_confirm_clear"):
        st.warning("Delete the whole usage history? This can't be undone.")
        c = st.columns([1, 1, 5])
        c[0].button("Delete", type="primary", on_click=_clear, args=(store,), width="stretch")
        c[1].button("Cancel", on_click=lambda: st.session_state.pop("admin_confirm_clear", None), width="stretch")
    else:
        st.button("Clear usage history…", on_click=lambda: st.session_state.update(admin_confirm_clear=True))
