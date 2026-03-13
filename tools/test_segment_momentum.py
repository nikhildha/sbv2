import os
import sys
import json
import pandas as pd

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from data_pipeline import _get_binance_client

def run_pulse_check():
    print("\n" + "=" * 90)
    print("  🔥 INSTITUTIONAL SEGMENT PULSE CHECK (LIVE 24H DATA) 🔥")
    print("=" * 90)

    client = _get_binance_client()
    try:
        tickers = client.get_ticker()
        ticker_map = {t["symbol"]: t for t in tickers}
    except Exception as e:
        print(f"❌ Failed to fetch tickers: {e}")
        return

    # 1. Fetch BTC Benchmark
    btc_ticker = ticker_map.get("BTCUSDT")
    if not btc_ticker:
        print("❌ Could not find BTCUSDT for benchmark.")
        return
    btc_return = float(btc_ticker["priceChangePercent"])
    print(f"📈 BENCHMARK: Bitcoin (BTC) 24H Return: {btc_return:+.2f}%")
    print("-" * 90)

    results = []

    for segment, coins in config.CRYPTO_SEGMENTS.items():
        segment_volume_usd = 0.0
        active_coins = []
        positive_coins = 0

        # Pass 1: Gather coins and total segment volume
        for symbol in coins:
            t = ticker_map.get(symbol)
            if t:
                try:
                    change = float(t["priceChangePercent"])
                    volume = float(t["quoteVolume"])
                    active_coins.append({"symbol": symbol, "change": change, "volume": volume})
                    segment_volume_usd += volume
                    if change > 0:
                        positive_coins += 1
                except (ValueError, TypeError):
                    pass

        if not active_coins or segment_volume_usd == 0:
            continue

        # Pass 2: Calculate Volume-Weighted Return (VW-RR)
        vw_return = 0.0
        for c in active_coins:
            weight = c["volume"] / segment_volume_usd
            vw_return += c["change"] * weight

        # Pass 3: Calculate Alpha
        alpha = vw_return - btc_return

        # Pass 4: Calculate Breadth
        breadth = positive_coins / len(active_coins)

        # Pass 5: The Composite Score Logic
        # If Alpha is positive, we amplify it by breadth (e.g. 100% breadth keeps it full, 20% breadth cuts it to 20%)
        # If Alpha is negative, we punish it MORE if breadth is bad (e.g. 20% breadth multiplies negative score by 1.8)
        if alpha >= 0:
            composite_score = alpha * breadth
        else:
            composite_score = alpha * (2.0 - breadth) # 2.0 - 0.2 = 1.8x penalty

        results.append({
            "segment": segment,
            "vw_return": vw_return,
            "alpha": alpha,
            "breadth": breadth,
            "composite": composite_score,
            "volume_m": segment_volume_usd / 1_000_000,
            "coin_count": len(active_coins)
        })

    # Sort by the final Institutional Composite Score
    results.sort(key=lambda x: x["composite"], reverse=True)

    print(f"  {'Rank':<5} | {'Segment':<8} | {'Comp Score':<12} | {'VW-Return':<11} | {'Alpha vs BTC':<14} | {'Breadth':<9} | {'24H Vol'}")
    print("-" * 90)

    for i, r in enumerate(results):
        rank = f"#{i+1}"
        seg = r["segment"]
        comp = f"{r['composite']:+.2f}"
        vwr = f"{r['vw_return']:+.2f}%"
        alpha = f"{r['alpha']:+.2f}%"
        breadth = f"{r['breadth']*100:.0f}%"
        vol = f"${r['volume_m']:,.0f}M"
        
        # Highlight top 2
        prefix = "👉" if i < 2 else "  "
        print(f"{prefix} {rank:<4} | {seg:<8} | {comp:<12} | {vwr:<11} | {alpha:<14} | {breadth:<9} | {vol}")

    print("-" * 90)
    print("🧠 LOGIC BREAKDOWN:")
    print(" • VW-Return:  Return weighted by dollar volume (stops tiny coins from faking momentum).")
    print(" • Alpha:      How much the segment beat Bitcoin.")
    print(" • Breadth:    % of coins in the segment that are green.")
    print(" • Comp Score: Alpha * Breadth (Amplifies true rotation, punishes poor participation).")
    print("=" * 90 + "\n")

if __name__ == "__main__":
    run_pulse_check()
