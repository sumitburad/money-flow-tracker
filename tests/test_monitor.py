from datetime import date, timedelta
import numpy as np
import pandas as pd
import pytest

from backend.run_daily import (
    calculate_trend, calculate_volume_flow, assign_label,
    momentum_tag, assess, source_fresh, trading_days_old
)
from backend.feed_contract import validate_feed


def fam(state, source="https://example.org", date="2026-11-13"):
    return {"state": state, "source": source if state != "not_available" else None,
            "observed_at": date, "evidence": "observed category"}


def families(flow="supportive", trend="supportive", macro="supportive"):
    return {
        "money_flow": fam(flow),
        "price_trend": fam(trend),
        "breadth": fam("not_available"),
        "positioning": fam("not_available"),
        "macro_liquidity": fam(macro),
        "news": fam("not_available"),
    }


def test_label_rules_no_scores():
    assert assign_label(families()) == ("Bullish", "Moderate")
    assert assign_label(families("opposing", "opposing", "opposing")) == ("Bearish", "Moderate")
    assert assign_label(families("not_available", "supportive"))[0] == "Neutral/Mixed"
    assert assign_label(families("supportive", "opposing"))[0] == "Neutral/Mixed"
    assert assign_label(families("supportive", "supportive", "opposing"))[0] == "Neutral/Mixed"


def test_trend_deterministic():
    up = np.linspace(100, 220, 240)
    down = up[::-1]
    assert calculate_trend(up) == "supportive"
    assert calculate_trend(down) == "opposing"
    assert calculate_trend([1, 2]) == "not_available"


def test_volume_is_participation_not_net_flow():
    close = np.array([100 + x * 0.4 + (2 if x % 2 else -2) for x in range(240)])
    volume = np.array([400 if x % 2 else 100 for x in range(240)])
    assert calculate_volume_flow(close, volume) == "supportive"
    assert calculate_volume_flow(close, np.zeros(240)) == "not_available"
    assert calculate_volume_flow(close[:15], volume[:15]) == "not_available"


def test_weekend_freshness():
    assert trading_days_old(date(2026, 11, 13), date(2026, 11, 15)) == 1
    assert source_fresh("2026-11-13", date(2026, 11, 15))
    assert not source_fresh("2026-11-05", date(2026, 11, 15))


def test_feed_rejects_bogus_fields_and_unattributed_direction():
    entry = {"id": "x", "item": "Test", "group": "sector",
             "symbol": "TEST", "region": "US", "currency": "USD",
             "label": "Neutral/Mixed", "tag": "Steady",
             "agreement": "Weak", "freshness": "current",
             "families": families("not_available", "not_available", "not_available")}
    feed = {"schema_version": "1.0", "usage": "research_only_not_order_authorization",
            "items": [entry], "macro": {}}
    assert validate_feed(feed)
    entry["smart_money_score"] = 70
    with pytest.raises(ValueError, match="forbidden"):
        validate_feed(feed)
    del entry["smart_money_score"]
    entry["label"] = "Bullish"
    with pytest.raises(ValueError, match="money flow"):
        validate_feed(feed)


def test_missing_market_data_safe(monkeypatch):
    import backend.run_daily as engine
    def unavailable(asset):
        raise ValueError("provider unavailable")
    monkeypatch.setattr(engine, "fetch_yfinance", unavailable)
    record = assess({"id": "test", "name": "Test", "group": "equity_market",
                     "region": "IN", "currency": "INR", "symbol": "TEST",
                     "asset_type": "equity"}, date(2026, 11, 15), {})
    assert record["label"] == "Neutral/Mixed"
    assert record["freshness"] == "unavailable"
    assert record["families"]["money_flow"]["state"] == "not_available"
    assert "smart_money_score" not in record


def test_momentum_has_defined_fallback():
    assert momentum_tag([1, 2, 3], [1, 2, 3]) == "Steady"
