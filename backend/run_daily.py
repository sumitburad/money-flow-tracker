import os
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
import yaml


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load_assets():
    path = os.path.join(ROOT, "backend", "assets.yaml")
    with open(path, "r") as file:
        config = yaml.safe_load(file)
    return config["assets"]


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def classify_trend(close, ma20, ma50):
    if pd.isna(ma20) or pd.isna(ma50):
        return "neutral"

    if close > ma20 > ma50:
        return "bullish"
    elif close < ma20 < ma50:
        return "bearish"
    else:
        return "neutral"


def calculate_score(row):
    score = 50

    if row["one_day_change_pct"] > 1:
        score += 8
    elif row["one_day_change_pct"] < -1:
        score -= 8

    if row["five_day_change_pct"] > 2:
        score += 10
    elif row["five_day_change_pct"] < -2:
        score -= 10

    if row["one_month_change_pct"] > 5:
        score += 10
    elif row["one_month_change_pct"] < -5:
        score -= 10

    if row["trend"] == "bullish":
        score += 10
    elif row["trend"] == "bearish":
        score -= 10

    if row["volume_signal"] is not None:
        if row["volume_signal"] >= 1.5:
            score += 8
        elif row["volume_signal"] < 0.7:
            score -= 4

    if row["rsi"] is not None:
        if 55 <= row["rsi"] <= 70:
            score += 5
        elif row["rsi"] < 35:
            score -= 5
        elif row["rsi"] > 75:
            score -= 5

    score = max(0, min(100, score))
    return round(score, 1)


def classify_flow(score):
    if score >= 80:
        return "Strong inflow / accumulation signal"
    elif score >= 60:
        return "Positive flow signal"
    elif score >= 40:
        return "Neutral or mixed signal"
    elif score >= 20:
        return "Selling pressure"
    else:
        return "Strong outflow / distribution signal"


def fetch_asset(asset):
    symbol = asset["symbol"]

    df = yf.download(
        symbol,
        period="1y",
        interval="1d",
        progress=False,
        auto_adjust=False,
        threads=False
    )

    if df.empty:
        raise ValueError(f"No data found for {symbol}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    df = df.dropna(subset=["Close"])
    df["RSI"] = calculate_rsi(df["Close"])
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()

    if "Volume" in df.columns:
        df["VolumeAvg20"] = df["Volume"].rolling(20).mean()
        df["VolumeSignal"] = df["Volume"] / df["VolumeAvg20"]
    else:
        df["VolumeSignal"] = np.nan

    latest = df.iloc[-1]
    previous = df.iloc[-2]

    close = float(latest["Close"])
    previous_close = float(previous["Close"])

    close_5d = float(df["Close"].iloc[-6]) if len(df) >= 6 else previous_close
    close_1m = float(df["Close"].iloc[-22]) if len(df) >= 22 else previous_close

    one_day = ((close / previous_close) - 1) * 100
    five_day = ((close / close_5d) - 1) * 100
    one_month = ((close / close_1m) - 1) * 100

    ma20 = latest["MA20"]
    ma50 = latest["MA50"]
    ma200 = latest["MA200"]
    rsi = latest["RSI"]
    volume_signal = latest["VolumeSignal"]

    trend = classify_trend(close, ma20, ma50)

    row = {
        "date": str(df.index[-1].date()),
        "asset_class": asset["class"],
        "instrument": asset["name"],
        "symbol": symbol,
        "current_price": round(close, 2),
        "previous_close": round(previous_close, 2),
        "one_day_change_pct": round(one_day, 2),
        "five_day_change_pct": round(five_day, 2),
        "one_month_change_pct": round(one_month, 2),
        "ma20": round(float(ma20), 2) if not pd.isna(ma20) else None,
        "ma50": round(float(ma50), 2) if not pd.isna(ma50) else None,
        "ma200": round(float(ma200), 2) if not pd.isna(ma200) else None,
        "rsi": round(float(rsi), 2) if not pd.isna(rsi) else None,
        "volume_signal": round(float(volume_signal), 2) if not pd.isna(volume_signal) else None,
        "trend": trend,
        "data_source": "yfinance",
        "data_freshness": "daily/delayed",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat()
    }

    row["smart_money_score"] = calculate_score(row)
    row["flow_direction"] = classify_flow(row["smart_money_score"])
    row["confidence"] = "medium"
    row["note"] = "This is an indirect flow signal based on price, trend, RSI, and volume. It is not direct institutional buying data."

    return row


def generate_markdown_report(summary):
    rows = summary["assets"]

    strongest = sorted(rows, key=lambda x: x["smart_money_score"], reverse=True)[:3]
    weakest = sorted(rows, key=lambda x: x["smart_money_score"])[:3]

    report = f"""# Daily Money Flow Tracker Report

Date: {summary["generated_at"]}

## 1. Market Regime

Regime: Mixed

Reason:
- This basic version uses price, trend, RSI, and volume signals.
- Direct institutional flow data like FII/DII, ETF flows, and 13F filings is not yet connected.

## 2. Top Asset Class Movements

| Asset | 1D % | 5D % | 1M % | Trend | Score | Flow |
|---|---:|---:|---:|---|---:|---|
"""

    for row in rows:
        report += f"| {row['instrument']} | {row['one_day_change_pct']} | {row['five_day_change_pct']} | {row['one_month_change_pct']} | {row['trend']} | {row['smart_money_score']} | {row['flow_direction']} |\n"

    report += """

## 3. Where Money Appears to Be Moving

Strongest signals:
"""

    for row in strongest:
        report += f"- {row['instrument']}: {row['flow_direction']} with score {row['smart_money_score']}\n"

    report += """

Weakest signals:
"""

    for row in weakest:
        report += f"- {row['instrument']}: {row['flow_direction']} with score {row['smart_money_score']}\n"

    report += """

## 4. Data Missing or Delayed

- FII/DII India data is not connected yet.
- ETF fund flow data is not connected yet.
- SEC 13F data is quarterly and delayed, not daily.
- News sentiment is not connected yet.
- Current score is based on indirect signals only.

## 5. Disclaimer

This is not financial advice. This is a market research tracker based on publicly available data and estimated signals.
"""

    return report


def generate_html(summary):
    rows = summary["assets"]

    html = """
<!DOCTYPE html>
<html>
<head>
    <title>Money Flow Tracker</title>
    <style>
        body { font-family: Arial, sans-serif; padding: 30px; background: #f7f7f7; }
        h1 { color: #111; }
        table { width: 100%; border-collapse: collapse; background: white; }
        th, td { padding: 10px; border: 1px solid #ddd; text-align: left; }
        th { background: #222; color: white; }
        .positive { color: green; }
        .negative { color: red; }
    </style>
</head>
<body>
    <h1>Money Flow Tracker</h1>
"""

    html += f"<p>Generated at: {summary['generated_at']}</p>"
    html += """
    <table>
        <tr>
            <th>Asset</th>
            <th>Class</th>
            <th>Price</th>
            <th>1D %</th>
            <th>5D %</th>
            <th>1M %</th>
            <th>Trend</th>
            <th>RSI</th>
            <th>Score</th>
            <th>Flow</th>
            <th>Confidence</th>
        </tr>
"""

    for row in rows:
        one_day_class = "positive" if row["one_day_change_pct"] >= 0 else "negative"

        html += f"""
        <tr>
            <td>{row['instrument']}</td>
            <td>{row['asset_class']}</td>
            <td>{row['current_price']}</td>
            <td class="{one_day_class}">{row['one_day_change_pct']}</td>
            <td>{row['five_day_change_pct']}</td>
            <td>{row['one_month_change_pct']}</td>
            <td>{row['trend']}</td>
            <td>{row['rsi']}</td>
            <td>{row['smart_money_score']}</td>
            <td>{row['flow_direction']}</td>
            <td>{row['confidence']}</td>
        </tr>
"""

    html += """
    </table>

    <p><b>Disclaimer:</b> This is not financial advice. Signals are estimated from public market data.</p>
</body>
</html>
"""

    return html


def main():
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "frontend"), exist_ok=True)

    assets = load_assets()
    results = []

    for asset in assets:
        try:
            print(f"Fetching {asset['name']}...")
            results.append(fetch_asset(asset))
        except Exception as error:
            print(f"Error fetching {asset['name']}: {error}")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": results
    }

    with open(os.path.join(ROOT, "data", "latest_summary.json"), "w") as file:
        json.dump(summary, file, indent=2)

    markdown_report = generate_markdown_report(summary)
    with open(os.path.join(ROOT, "reports", "latest_report.md"), "w") as file:
        file.write(markdown_report)

    html = generate_html(summary)
    with open(os.path.join(ROOT, "frontend", "index.html"), "w") as file:
        file.write(html)

    print("Done. Files created:")
    print("- data/latest_summary.json")
    print("- reports/latest_report.md")
    print("- frontend/index.html")


if __name__ == "__main__":
    main()