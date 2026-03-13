import os
import sys
import pandas as pd
from datetime import datetime

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# FORCE PAPER TRADE FOR TESTING (Routes Data to Binance)
config.PAPER_TRADE = True
config.MULTI_TF_CANDLE_LIMIT = 500 # Force 500 candles so HMMs have enough data to train

# Hotfix Binance Ticker Migrations for the test script
for seg in config.CRYPTO_SEGMENTS:
    config.CRYPTO_SEGMENTS[seg] = [
        "RENDERUSDT" if x == "RNDRUSDT" else x for x in config.CRYPTO_SEGMENTS[seg]
    ]
    config.CRYPTO_SEGMENTS[seg] = [
        "POLUSDT" if x == "MATICUSDT" else x for x in config.CRYPTO_SEGMENTS[seg]
    ]

from data_pipeline import _fetch_klines_binance
from feature_engine import compute_hmm_features, compute_all_features
from hmm_brain import MultiTFHMMBrain
import coin_scanner

def direct_binance_mtf_fetch(symbol, limit):
    return {
        "15m": _fetch_klines_binance(symbol, "15m", limit),
        "1h": _fetch_klines_binance(symbol, "1h", limit),
        "1d": _fetch_klines_binance(symbol, "1d", limit)
    }

def run_segment_simulation():
    print("\n" + "=" * 90)
    print("  🏆 INSTITUTIONAL PIPELINE EXPERIMENT 🏆")
    print("=" * 90)

    # 1. Get the Top Segments
    top_segments = coin_scanner.get_hottest_segments(segment_limit=2)
    print("\n🔥 STEP 1: SEGMENT MOMENTUM PULSE CHECK")
    print("-" * 90)
    print(f"Top 2 Rotational Segments Chosen: {', '.join(top_segments)}")

    # 2. Get the Coins
    candidates = []
    for seg in top_segments:
        coins = config.CRYPTO_SEGMENTS.get(seg, [])
        for c in coins:
            candidates.append({"symbol": c, "segment": seg})
            
    # Filter out exclusions just to be safe
    exclusions = coin_scanner.get_all_exclusions()
    candidates = [c for c in candidates if c["symbol"] not in exclusions]

    print(f"Total Candidates Extracted: {len(candidates)} Coins")
    for c in candidates:
        print(f"  - {c['symbol']} ({c['segment']})")

    print("\n🧠 STEP 2: MULTI-TIMEFRAME HMM ANALYSIS")
    print("-" * 90)
    
    results = []

    for c in candidates:
        symbol = c["symbol"]
        segment = c["segment"]
        print(f"Fetching 1D, 1H, and 15M candles for {symbol}...")
        
        # Fetch Multi-TF Data (Forced directly to Binance for testing)
        tf_data = direct_binance_mtf_fetch(symbol, limit=config.MULTI_TF_CANDLE_LIMIT)
        
        if not tf_data or tf_data.get("15m") is None or tf_data.get("1h") is None or tf_data.get("1d") is None:
            print(f"  ❌ Skipped {symbol}: Insufficient historical data.")
            continue
            
        from hmm_brain import HMMBrain
        brain = MultiTFHMMBrain(symbol)
        
        has_trained_model = False
        for tf in config.MULTI_TF_TIMEFRAMES:
            df_tf = tf_data.get(tf)
            if df_tf is not None and not df_tf.empty:
                df_hmm = compute_hmm_features(df_tf)
                single_brain = HMMBrain(symbol=symbol)
                single_brain.train(df_hmm)
                if single_brain.is_trained:
                    brain.set_brain(tf, single_brain)
                    has_trained_model = True
        
        if not has_trained_model or not brain.is_ready():
            print(f"  ❌ Skipped {symbol}: Multi-TF HMM models failed to converge.")
            continue
            
        # Enrich tf_data so predict() has access to features
        enriched_tf_data = {}
        for tf, df_tf in tf_data.items():
             if df_tf is not None and not df_tf.empty:
                 enriched_tf_data[tf] = compute_all_features(df_tf.copy())
            
        # Run Prediction
        brain.predict(enriched_tf_data)
            
        # Get live data for scoring
        df_15m = tf_data["15m"]
        current_price = df_15m["close"].iloc[-1]
        
        # We already enriched above, but need ATR explicitly
        df_feat = enriched_tf_data.get("15m", df_15m)
        current_atr = df_feat["atr_14"].iloc[-1] if "atr_14" in df_feat.columns else 0
        
        # Calculate Conviction 
        conviction, consensus, tf_agreement = brain.get_conviction()
        regime_summary = brain.get_regime_summary()
        
        # Grab the max probability from the 15m brain for the simple 'conf' printout
        conf = 0
        if "15m" in brain._predictions:
             conf = brain._predictions["15m"][1]
        
        # Determine Trade Action based on Regime
        action = "WAIT"
        if consensus == "BUY":
            action = "GO LONG 🟢"
        elif consensus == "SELL":
             action = "GO SHORT 🔴"
             
        results.append({
            "symbol": symbol,
            "segment": segment,
            "action": action,
            "regime": regime_summary,
            "confidence": conf * 100,
            "conviction": conviction,
            "tf_agreement": tf_agreement,
            "price": current_price
        })

    print("\n📊 STEP 3: CONVICTION SORTING & CORRELATION CONTROL")
    print("-" * 90)
    
    # Sort all coins strictly by the calculated Conviction Score (Highest First)
    results.sort(key=lambda x: x["conviction"], reverse=True)
    
    for i, r in enumerate(results):
        rank = f"#{i+1}"
        sym = f"{r['symbol']} ({r['segment']})"
        action = f"{r['action']}"
        conv = f"{r['conviction']:.1f}"
        conf = f"{r['confidence']:.1f}%"
        reg = f"{r['regime']}"
        print(f"{rank:<4} | {sym:<18} | {action:<12} | Conviction: {conv:<5} | Conf: {conf:<6} | {reg}")
        
    print("-" * 90)
    print("\n🚫 CORRELATION FIREWALL (BEST-IN-CLASS ENFORCEMENT)")
    print("-" * 90)
    
    deployed_segments = set()
    final_trades = []
    
    for r in results:
        # We only deploy if action is LONG or SHORT
        if "LONG" in r["action"] or "SHORT" in r["action"]:
            segment = r["segment"]
            symbol = r["symbol"]
            
            # Check Max 1-per-segment rule
            if segment in deployed_segments:
                print(f"  ❌ REJECTED {symbol:<8}: Correlation Risk. We already drafted the best {segment} asset.")
            else:
                print(f"  ✅ DRAFTED  {symbol:<8}: #1 Ranked {segment} asset by Conviction Score.")
                deployed_segments.add(segment)
                final_trades.append(r)
        
    print("\n💰 FINAL DEPLOYMENT:")
    print("-" * 90)
    if not final_trades:
         print("  No technical breakouts passed the Multi-TF Conviction thresholds.")
    for t in final_trades:
         print(f"  Deploying Trade -> {t['action']} on {t['symbol']} at ${t['price']:.4f}")
         
    print("=" * 90 + "\n")

if __name__ == "__main__":
    run_segment_simulation()
