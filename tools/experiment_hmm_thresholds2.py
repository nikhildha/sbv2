#!/usr/bin/env python3
"""
tools/experiment_hmm_thresholds2.py

Tests varying margin confidence thresholds using actual backtester RM3_Swing and RM2_ATR logic.
"""

import sys
import os
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_engine import compute_hmm_features
from data_pipeline import fetch_klines

# --- CONFIGURATION ---
TEST_COINS = ["BTCUSDT", "DOGEUSDT", "ARBUSDT", "AAVEUSDT", "FILUSDT"]
INTERVAL = "15m"
LIMIT = 17267 # ~6 months 
N_TRAIN = 30 * 96 # 30 days
STEP_BARS = 14 * 96 # 14 days retrain
THRESHOLDS = [0.0, 0.40, 0.50, 0.60, 0.70, 0.80]
LEVERAGE = 35
FEE = 0.0005

def state_map_3(model):
    """Sort states logically so 0=BULL, 1=BEAR, 2=CHOP (based on mean returns)."""
    idx = np.argsort(model.means_[:, 0])[::-1]
    return {int(idx[0]): 0, int(idx[1]): 2, int(idx[2]): 1}

def margin_conf(probs):
    """best_prob - second_best_prob"""
    s = np.sort(probs, axis=1)[:, ::-1]
    return s[:, 0] - s[:, 1]

class Trade:
    def __init__(self, rm_id, entry_idx, entry_price, direction, atr, swing_lh):
        self.rm_id = rm_id
        self.entry_idx = entry_idx
        self.entry_price = entry_price
        self.direction = direction
        self.status = "OPEN"
        self.highest_high = entry_price
        self.lowest_low = entry_price
        self.max_adverse_excursion = 0.0 
        self.returns = [] 
        
        if rm_id == "RM2_ATR":
            self.sl_price = entry_price - direction * (3.5 * atr)
        elif rm_id == "RM3_Swing":
            self.sl_price = swing_lh

    def update(self, idx, high, low, close, current_regime):
        if self.status != "OPEN": return
        
        if high > self.highest_high: self.highest_high = high
        if low < self.lowest_low: self.lowest_low = low
        
        adv_p = low if self.direction == 1 else high
        mae = ((adv_p - self.entry_price) / self.entry_price) * self.direction
        if mae < self.max_adverse_excursion:
            self.max_adverse_excursion = mae
            
        if self.sl_price:
            if self.direction == 1 and low <= self.sl_price:
                self.close_trade(self.sl_price)
                return
            if self.direction == -1 and high >= self.sl_price:
                self.close_trade(self.sl_price)
                return

    def close_trade(self, price):
        if self.status != "OPEN": return
        self.status = "CLOSED"
        ret = (price - self.entry_price) / self.entry_price
        self.returns.append((1.0, ret * self.direction))
            
    def calculate_pnl(self, leverage):
        if self.max_adverse_excursion * leverage <= -1.0:
            return -100.0
        
        total_pnl = 0
        rem_cap = 100.0
        for frac, r in self.returns:
            cap_used = rem_cap * frac
            pnl = cap_used * r * leverage
            fees = (cap_used + cap_used * (1 + r * leverage)) * FEE
            total_pnl += pnl - fees
            rem_cap -= cap_used
        return total_pnl

def run_threshold_experiment():
    print("\n" + "="*80)
    print("  HMM THRESHOLD OPTIMIZATION EXPERIMENT (FULL SIMULATION)")
    print(f"  Testing basket: {TEST_COINS}")
    print("="*80)

    results = {th: {"trades": 0, "wins": 0, "total_pnl": 0.0} for th in THRESHOLDS}
    
    btc_df = fetch_klines("BTCUSDT", INTERVAL, limit=LIMIT)
    
    for coin in TEST_COINS:
        print(f"\n  Fetching and computing {coin}...")
        df = fetch_klines(coin, INTERVAL, limit=LIMIT)
        if df is None or len(df) < N_TRAIN + 100:
            continue
            
        df['tr0'] = abs(df['high'] - df['low'])
        df['tr1'] = abs(df['high'] - df['close'].shift())
        df['tr2'] = abs(df['low'] - df['close'].shift())
        df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
        df['atr'] = df['tr'].rolling(14).mean()
        df['swing_l'] = df['low'].rolling(10).min()
        df['swing_h'] = df['high'].rolling(10).max()
        
        df_feat = compute_hmm_features(df, btc_df if coin != "BTCUSDT" else None)
        df_feat = df_feat.dropna().reset_index(drop=True)
        # Re-align df
        df = df.loc[df.index.isin(df_feat.index)].reset_index(drop=True)
        
        from hmm_brain import HMM_FEATURES
        X_all = df_feat[HMM_FEATURES].values
        
        # Test all thresholds at once
        open_trades = {th: None for th in THRESHOLDS}
        
        model = None
        sm = None
        mu = None
        std = None
        current_regime = 2
        last_margin = 0.0
        
        # Use RM3 for alts, RM2 for L1s based on previous report
        rm_id = "RM2_ATR" if coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"] else "RM3_Swing"
        
        for i in range(N_TRAIN, len(X_all)):
            # Retrain
            if i == N_TRAIN or (i - N_TRAIN) % STEP_BARS == 0:
                X_train = X_all[i - N_TRAIN:i]
                mu, std = X_train.mean(axis=0), X_train.std(axis=0)
                std[std < 1e-10] = 1e-10
                X_train_s = (X_train - mu) / std
                try:
                    m = GaussianHMM(n_components=3, covariance_type="full", n_iter=100, random_state=42)
                    m.fit(X_train_s)
                    model = m
                    sm = state_map_3(m)
                except Exception:
                    pass
            
            if model is None: continue
            
            # Predict
            X_test_s = (X_all[i:i+1] - mu) / std
            probs = model.predict_proba(X_test_s)
            raw_state = model.predict(X_test_s)[0]
            current_regime = sm.get(raw_state, 2)
            last_margin = margin_conf(probs)[0]
            
            row = df.iloc[i]
            
            # 1. Update existing trades
            for th, t in open_trades.items():
                if t is not None:
                    t.update(i, row['high'], row['low'], row['close'], current_regime)
                    
                    # Close on flip
                    if (t.direction == 1 and current_regime != 0) or (t.direction == -1 and current_regime != 1):
                        t.close_trade(row['close'])
                        
                    if t.status == "CLOSED":
                        pnl = t.calculate_pnl(LEVERAGE)
                        results[th]["trades"] += 1
                        results[th]["total_pnl"] += pnl
                        if pnl > 0: results[th]["wins"] += 1
                        open_trades[th] = None
                        
            # 2. Open new trades 
            for th in THRESHOLDS:
                if open_trades[th] is None:
                    if float(last_margin) >= th:
                        if current_regime == 0: # BULL
                            open_trades[th] = Trade(rm_id, i, row['close'], 1, row['atr'], row['swing_l'])
                        elif current_regime == 1: # BEAR
                            open_trades[th] = Trade(rm_id, i, row['close'], -1, row['atr'], row['swing_h'])
                        

    # --- PRINT FINAL METRICS ---
    print("\n" + "="*80)
    print(f"  RESULTS {LEVERAGE}x LEVERAGE USING FULL TRADE LOGIC:")
    print("="*80)
    
    print(f"{'Threshold':<12} | {'Trades':<8} | {'Win Rate':<10} | {'Sum PnL $':<12}")
    print("-" * 55)
    
    for th in THRESHOLDS:
        data = results[th]
        n = data["trades"]
        if n == 0: continue
        win_rate = data["wins"] / n
        total_pnl = data["total_pnl"]
        print(f">= {th*100:2.0f}%     | {n:<8} | {win_rate*100:5.2f}%    | ${total_pnl:<12.2f}")

if __name__ == "__main__":
    run_threshold_experiment()
