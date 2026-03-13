#!/usr/bin/env python3
"""
tools/experiment_hmm_thresholds.py

Tests varying margin confidence thresholds (40%, 50%, 60%, 70%, 80%) on a basket of top cryptocoins
to observe the empirical impact on Trade Frequency (N), Win Rate, and Net PnL.
"""

import sys
import os
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_engine import compute_hmm_features
from data_pipeline import fetch_klines

# --- CONFIGURATION ---
TEST_COINS = ["BTCUSDT", "DOGEUSDT", "ARBUSDT", "AAVEUSDT", "FILUSDT"]
INTERVAL = "4h"
LIMIT = 2000 # ~11 months
N_TRAIN = 400
FORWARD_H = 12 # 48h holding period for standardizing returns
THRESHOLDS = [0.0, 0.40, 0.50, 0.60, 0.70, 0.80]

def state_map_3(model):
    """Sort states logically so 0=BULL, 1=BEAR, 2=CHOP (based on mean returns)."""
    idx = np.argsort(model.means_[:, 0])[::-1]
    return {int(idx[0]): 0, int(idx[1]): 2, int(idx[2]): 1}

def margin_conf(probs):
    """best_prob - second_best_prob"""
    s = np.sort(probs, axis=1)[:, ::-1]
    return s[:, 0] - s[:, 1]

def run_threshold_experiment():
    print("\n" + "="*80)
    print("  HMM THRESHOLD OPTIMIZATION EXPERIMENT")
    print(f"  Testing basket: {TEST_COINS}")
    print(f"  Holding period: {FORWARD_H * 4} hours")
    print("="*80)

    # Dictionary to collect aggregated metrics per threshold
    results = {th: {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "returns": []} for th in THRESHOLDS}
    
    btc_df = fetch_klines("BTCUSDT", INTERVAL, limit=LIMIT)
    
    for coin in TEST_COINS:
        print(f"\n  Fetching and computing {coin}...")
        df_raw = fetch_klines(coin, INTERVAL, limit=LIMIT)
        if df_raw is None or len(df_raw) < N_TRAIN + FORWARD_H:
            print(f"    Skipping {coin}: Insufficient data.")
            continue
            
        # Get baseline features used by primary model
        df_feat = compute_hmm_features(df_raw, btc_df if coin != "BTCUSDT" else None)
        df_feat = df_feat.dropna()
        
        from hmm_brain import HMM_FEATURES
        X_all = df_feat[HMM_FEATURES].values
        
        # Calculate forward returns shifted (simulating taking the trade and checking result later)
        fwd_returns = np.log(df_raw["close"].shift(-FORWARD_H) / df_raw["close"])
        fwd_returns = fwd_returns.reindex(df_feat.index).values
        
        # Walk forward validation
        step = 50
        for i in range(N_TRAIN, len(X_all) - FORWARD_H, step):
            test_idx = i
            
            # Train window
            X_train = X_all[i - N_TRAIN:i]
            mu, std = X_train.mean(axis=0), X_train.std(axis=0)
            std[std < 1e-10] = 1e-10
            X_train_s = (X_train - mu) / std
            
            try:
                model = GaussianHMM(n_components=3, covariance_type="full", n_iter=100, random_state=42)
                model.fit(X_train_s)
                sm = state_map_3(model)
                
                # Predict ONE snapshot out of sample
                X_test = X_all[test_idx:test_idx+1]
                X_test_s = (X_test - mu) / std
                
                probs = model.predict_proba(X_test_s)
                raw_state = model.predict(X_test_s)[0]
                mapped_state = sm.get(raw_state, 2)
                
                margin = margin_conf(probs)[0]
                actual_return = fwd_returns[test_idx]
                
                if np.isnan(actual_return):
                    continue
                    
                # Signal logic
                is_bull = mapped_state == 0
                is_bear = mapped_state == 1
                
                if not (is_bull or is_bear):
                    continue # Ignore chop
                    
                trade_return = actual_return if is_bull else -actual_return
                is_win = trade_return > 0
                
                # Test the prediction against all thresholds
                for th in THRESHOLDS:
                    if margin >= th:
                        results[th]["trades"] += 1
                        results[th]["total_pnl"] += trade_return
                        results[th]["returns"].append(trade_return)
                        if is_win:
                            results[th]["wins"] += 1
                        else:
                            results[th]["losses"] += 1
                            
            except Exception as e:
                # E.g. HMM fitting singular matrix
                continue
                
    # --- PRINT FINAL METRICS ---
    print("\n" + "="*80)
    print("  RESULTS AGGREGATED ACROSS BASKET:")
    print("="*80)
    
    print(f"{'Threshold':<12} | {'Trades':<8} | {'Win Rate':<10} | {'Sum Return':<12} | {'Avg Return':<12} | {'Sharpe':<8}")
    print("-" * 75)
    
    for th in THRESHOLDS:
        data = results[th]
        n = data["trades"]
        
        if n == 0:
            print(f">={th:.0%}   | {n:<8} | {'N/A':<10} | {'N/A':<12} | {'N/A':<12} | {'N/A':<8}")
            continue
            
        win_rate = data["wins"] / n
        total_pnl = data["total_pnl"]
        avg_ret = total_pnl / n
        
        returns_array = np.array(data["returns"])
        # Simplified sharpe: Mean / StdDev * sqrt(periods in year). Assuming 4h holding periods (6 periods a day = 2190 periods a yr)
        sharpe = (returns_array.mean() / (returns_array.std() + 1e-10)) * np.sqrt((365*24)/FORWARD_H)
        
        print(f">= {th*100:2.0f}%     | {n:<8} | {win_rate*100:5.2f}%    | {total_pnl*100:8.2f}%   | {avg_ret*100:8.2f}%   | {sharpe:5.2f}")

    print("\n* Sum Return is raw un-leveraged percent accumulation.")
    print("* Avg Return is expected return per trade.")

if __name__ == "__main__":
    run_threshold_experiment()
