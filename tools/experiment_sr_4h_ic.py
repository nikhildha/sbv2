#!/usr/bin/env python3
"""
tools/experiment_sr_4h_ic.py

Measures Information Coefficient (IC) of 4h Support/Resistance + VWAP
signals at multiple lookback windows to determine the optimal
CONVICTION_WEIGHT_SR_VWAP and SR lookback for production.

Previous EXP3 IC for SR was measured with sr_position=None (broken — never
wired up). Now that 4h S/R is properly wired, this re-measures the true IC.

Experiments:
  EXP A — SR lookback sweep: IC at 50 / 100 / 150 / 200 bars on 4h
  EXP B — Component breakdown: sr_pos IC vs vwap_pos IC vs combined
  EXP C — Signal-based Sharpe at each lookback (position ∝ signal strength)
  EXP D — Weight recommendation vs other factors (context from EXP3)

RESULTS ONLY — does NOT modify any production code.

Run:  python tools/experiment_sr_4h_ic.py
Expected runtime: 3–6 min (no HMM fitting — pure signal IC)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("hmmlearn.base").setLevel(logging.ERROR)

import numpy as np
import pandas as pd
from scipy import stats

# ─── Configuration ─────────────────────────────────────────────────────────────

TEST_COINS = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
    "AAVEUSDT", "WLDUSDT", "ETCUSDT", "FETUSDT", "BCHUSDT",
    "ZECUSDT", "PEPEUSDT", "ENAUSDT", "SOLUSDT", "LINKUSDT",
]

LOOKBACKS    = [50, 100, 150, 200]   # 4h bars: 8d / 16d / 25d / 33d
VWAP_WINDOW  = 20                    # rolling VWAP window (same as production)
FORWARD_H    = 12                    # 12 × 4h = 48h forward return
N_TRAIN      = 400                   # skip first N bars (warm-up)

# IC from EXP3 for context/weight scaling
HMM_IC_FROM_EXP3   = 0.1355
HMM_WEIGHT_CURRENT = 44

# ─── Data Fetcher ──────────────────────────────────────────────────────────────

_client = None

def _get_client():
    global _client
    if _client is None:
        from binance.client import Client
        _client = Client(tld="com")
    return _client


def fetch_ohlcv(symbol, interval="4h", start="2022-06-01", end="2026-03-01"):
    try:
        client = _get_client()
        klines = client.get_historical_klines(symbol, interval, start, end)
        if not klines:
            return None
        df = pd.DataFrame(klines, columns=[
            "ts", "open", "high", "low", "close", "volume",
            "ct", "qa", "t", "tb", "tq", "i",
        ])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df[["ts", "open", "high", "low", "close", "volume"]].set_index("ts")
    except Exception as e:
        print(f"  [WARN] fetch failed {symbol}: {e}")
        return None


# ─── Signal Computation (vectorized) ──────────────────────────────────────────

def compute_sr_signal_series(df, lookback):
    """
    Vectorized rolling SR position: where is close within the lookback-bar range?
    Returns:
      sr_pos  — 0 = at range low (support), 1 = at range high (resistance)
      sr_buy  — 1 - sr_pos  (high score = at support = bullish)
    """
    high_roll = df["high"].rolling(lookback).max()
    low_roll  = df["low"].rolling(lookback).min()
    sr_range  = (high_roll - low_roll).replace(0, np.nan)
    sr_pos    = ((df["close"] - low_roll) / sr_range).clip(0, 1)
    sr_buy    = 1.0 - sr_pos          # BUY signal: low in range = at support
    return sr_pos, sr_buy


def compute_vwap_signal_series(df, window=VWAP_WINDOW):
    """
    Rolling VWAP position: (close - VWAP) / VWAP
    Positive = above VWAP (bullish), negative = below.
    """
    typical  = (df["high"] + df["low"] + df["close"]) / 3
    cum_tpv  = (typical * df["volume"]).rolling(window).sum()
    cum_vol  = df["volume"].rolling(window).sum().replace(0, np.nan)
    vwap     = cum_tpv / cum_vol
    vwap_pos = (df["close"] - vwap) / vwap.replace(0, np.nan)
    return vwap_pos.clip(-0.5, 0.5)   # clip extreme values


def compute_combined_signal(sr_buy, vwap_pos):
    """
    Mimics _score_sr_vwap() weighting:
      60% weight on SR position, 40% weight on VWAP position (normalised).
    Range: approximately 0 → 1 (higher = stronger BUY conviction).
    """
    vwap_contrib = vwap_pos.clip(0, None) / 0.5   # 0 when below VWAP, 1 when +50% above
    return (sr_buy * 0.6 + vwap_contrib * 0.4).clip(0, 1)


# ─── IC Measurement ────────────────────────────────────────────────────────────

def compute_ic(signal_series, fwd_returns, n_train=N_TRAIN):
    """Pearson IC of signal vs forward return on the out-of-sample portion."""
    sig = signal_series.values
    fwd = fwd_returns.values
    mask = ~(np.isnan(sig) | np.isnan(fwd))
    mask[:n_train] = False          # skip warm-up
    if mask.sum() < 50:
        return np.nan, np.nan
    r, p = stats.pearsonr(sig[mask], fwd[mask])
    n = mask.sum()
    t = r * np.sqrt(n - 2) / np.sqrt(1 - r**2 + 1e-12)
    return r, t


def compute_sharpe(signal_series, fwd_returns, n_train=N_TRAIN, threshold=0.55):
    """
    Simple signal-based Sharpe: go long when combined_signal > threshold.
    Position size proportional to signal strength above threshold.
    """
    sig = signal_series.values
    fwd = fwd_returns.values
    mask = ~(np.isnan(sig) | np.isnan(fwd))
    mask[:n_train] = False

    if mask.sum() < 50:
        return np.nan

    s = sig[mask]
    r = fwd[mask]
    pos = np.where(s > threshold, s - threshold, 0.0)  # long-only
    pnl = pos * r
    if pnl.std() < 1e-10:
        return 0.0
    return pnl.mean() / pnl.std() * np.sqrt(365 * 6)   # 4h → annualised (6×4h/day)


# ─── Per-Coin Analysis ─────────────────────────────────────────────────────────

def analyse_coin(symbol, df):
    """Return IC and Sharpe for all lookbacks + VWAP + combined."""
    fwd_ret = np.log(df["close"].shift(-FORWARD_H) / df["close"])   # 48h fwd return

    results = {}
    for lb in LOOKBACKS:
        _, sr_buy = compute_sr_signal_series(df, lb)
        vwap_pos  = compute_vwap_signal_series(df)
        combined  = compute_combined_signal(sr_buy, vwap_pos)

        sr_ic,   sr_t   = compute_ic(sr_buy,   fwd_ret)
        vwap_ic, vwap_t = compute_ic(vwap_pos, fwd_ret)
        comb_ic, comb_t = compute_ic(combined,  fwd_ret)

        sr_sh   = compute_sharpe(sr_buy,   fwd_ret)
        comb_sh = compute_sharpe(combined,  fwd_ret)

        results[lb] = {
            "sr_ic":    sr_ic,   "sr_t":    sr_t,
            "vwap_ic":  vwap_ic, "vwap_t":  vwap_t,
            "comb_ic":  comb_ic, "comb_t":  comb_t,
            "sr_sh":    sr_sh,   "comb_sh": comb_sh,
        }
    return results


# ─── Aggregation ───────────────────────────────────────────────────────────────

def aggregate(all_results, metric):
    """Mean metric across all coins for each lookback."""
    rows = {}
    for lb in LOOKBACKS:
        vals = [r[lb][metric] for r in all_results if lb in r and not np.isnan(r[lb][metric])]
        rows[lb] = np.mean(vals) if vals else np.nan
    return rows


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 72)
    print("  EXPERIMENT: 4H S/R IC ANALYSIS — Optimal Lookback + Weight")
    print("=" * 72)
    print(f"  Coins: {len(TEST_COINS)}  |  Forward horizon: {FORWARD_H}×4h = 48h")
    print(f"  Lookbacks tested: {[f'{lb}×4h={lb*4}h' for lb in LOOKBACKS]}")
    print("=" * 72)

    # ── Fetch data ──────────────────────────────────────────────────────────────
    all_results = []
    fetched     = 0
    for i, sym in enumerate(TEST_COINS):
        print(f"  [{i+1:2d}/{len(TEST_COINS)}] {sym}...", end=" ", flush=True)
        df = fetch_ohlcv(sym)
        if df is None or len(df) < N_TRAIN + FORWARD_H + max(LOOKBACKS) + 20:
            print("skip (insufficient data)")
            continue
        coin_res = analyse_coin(sym, df)
        all_results.append(coin_res)
        fetched += 1
        best_comb_ic = max(coin_res[lb]["comb_ic"] for lb in LOOKBACKS
                           if not np.isnan(coin_res[lb]["comb_ic"]))
        print(f"ok  (best comb IC = {best_comb_ic:+.4f})")

    if not all_results:
        print("\n[ERROR] No data fetched.")
        return

    print(f"\n  Coins successfully analysed: {fetched}/{len(TEST_COINS)}")

    # ── EXP A: SR IC by lookback ─────────────────────────────────────────────
    print("\n" + "─" * 72)
    print("  EXP A — SR Position IC by 4h Lookback")
    print("─" * 72)
    print(f"  {'Lookback':<18} {'SR IC':>8} {'SR t-stat':>10} {'VWAP IC':>9} {'VWAP t':>8} {'Comb IC':>9} {'Comb t':>8}")
    print("  " + "-" * 68)

    sr_ics   = aggregate(all_results, "sr_ic")
    sr_ts    = aggregate(all_results, "sr_t")
    vwap_ics = aggregate(all_results, "vwap_ic")
    vwap_ts  = aggregate(all_results, "vwap_t")
    comb_ics = aggregate(all_results, "comb_ic")
    comb_ts  = aggregate(all_results, "comb_t")

    best_lb      = None
    best_comb_ic = -np.inf
    for lb in LOOKBACKS:
        lb_label = f"{lb}×4h ({lb*4}h / {lb*4//24}d)"
        sr_ic = sr_ics[lb]; sr_t = sr_ts[lb]
        vi    = vwap_ics[lb]; vt  = vwap_ts[lb]
        ci    = comb_ics[lb]; ct  = comb_ts[lb]
        marker = "  ← best" if ci == max(comb_ics[l] for l in LOOKBACKS if not np.isnan(comb_ics[l])) else ""
        print(f"  {lb_label:<18} {sr_ic:>+8.4f} {sr_t:>+10.2f} {vi:>+9.4f} {vt:>+8.2f} {ci:>+9.4f} {ct:>+8.2f}{marker}")
        if not np.isnan(ci) and ci > best_comb_ic:
            best_comb_ic = ci
            best_lb = lb

    # ── EXP B: Component breakdown at best lookback ──────────────────────────
    print("\n" + "─" * 72)
    print(f"  EXP B — Component Breakdown at Best Lookback ({best_lb}×4h = {best_lb*4}h)")
    print("─" * 72)
    print(f"  {'Signal':<28} {'IC':>8} {'t-stat':>10}  {'Interpretation'}")
    print("  " + "-" * 68)

    sr_ic_b  = sr_ics[best_lb]
    vwap_ic_b = vwap_ics[best_lb]
    comb_ic_b = comb_ics[best_lb]
    sr_t_b   = sr_ts[best_lb]
    vwap_t_b = vwap_ts[best_lb]
    comb_t_b = comb_ts[best_lb]

    def sig_label(t): return "✓ significant" if abs(t) > 2.0 else "~ weak"

    print(f"  {'SR pos (1-sr_pos, BUY signal)':<28} {sr_ic_b:>+8.4f} {sr_t_b:>+10.2f}  {sig_label(sr_t_b)}")
    print(f"  {'VWAP pos (above VWAP = bullish)':<28} {vwap_ic_b:>+8.4f} {vwap_t_b:>+10.2f}  {sig_label(vwap_t_b)}")
    print(f"  {'Combined (0.6×SR + 0.4×VWAP)':<28} {comb_ic_b:>+8.4f} {comb_t_b:>+10.2f}  {sig_label(comb_t_b)}")

    # ── EXP C: Signal-based Sharpe ───────────────────────────────────────────
    print("\n" + "─" * 72)
    print("  EXP C — Signal-Based Sharpe by Lookback")
    print("─" * 72)
    print(f"  {'Lookback':<18} {'SR Sharpe':>12} {'Comb Sharpe':>14}")
    print("  " + "-" * 48)

    sr_shs   = aggregate(all_results, "sr_sh")
    comb_shs = aggregate(all_results, "comb_sh")

    for lb in LOOKBACKS:
        lb_label = f"{lb}×4h ({lb*4//24}d)"
        marker = "  ← best" if lb == best_lb else ""
        print(f"  {lb_label:<18} {sr_shs[lb]:>12.3f} {comb_shs[lb]:>14.3f}{marker}")

    # ── EXP D: Weight recommendation ─────────────────────────────────────────
    print("\n" + "─" * 72)
    print("  EXP D — Weight Recommendation")
    print("─" * 72)

    # Scale weight by IC ratio relative to HMM
    # IC ratio method: w_sr = (IC_sr / IC_hmm) * w_hmm
    ic_ratio     = abs(comb_ic_b) / HMM_IC_FROM_EXP3
    raw_weight   = ic_ratio * HMM_WEIGHT_CURRENT
    # Round to nearest whole number, min 2 (don't go below current)
    rec_weight   = max(2, round(raw_weight))
    # Corresponding HMM reduction to keep sum = 100
    hmm_adj      = HMM_WEIGHT_CURRENT - (rec_weight - 2)   # 2 = current SR weight
    total_check  = hmm_adj + 7 + 11 + rec_weight + 11 + 0 + 15 + 10  # all other weights fixed

    print(f"\n  Reference ICs (from EXP3 on same 15 coins, same 4h data):")
    print(f"    HMM direction × margin : IC = +{HMM_IC_FROM_EXP3:.4f}  (weight = {HMM_WEIGHT_CURRENT})")
    print(f"    Funding rate proxy      : IC = -0.0190  (weight = 11)")
    print(f"    OI change proxy         : IC = +0.0160  (weight = 11)")
    print(f"    BTC macro               : IC = +0.0181  (weight = 7)")
    print(f"\n  4h S/R (this experiment):")
    print(f"    Combined SR+VWAP        : IC = {comb_ic_b:+.4f}  (t = {comb_t_b:+.2f})")
    print(f"    Best lookback           : {best_lb}×4h = {best_lb*4}h / {best_lb*4//24} days")
    print(f"\n  IC-ratio scaling: |{comb_ic_b:.4f}| / {HMM_IC_FROM_EXP3:.4f} × {HMM_WEIGHT_CURRENT} = {raw_weight:.1f} pts")
    print(f"\n  ┌─────────────────────────────────────────────────────────┐")
    print(f"  │  RECOMMENDATION                                         │")
    print(f"  │                                                         │")
    print(f"  │  CONVICTION_WEIGHT_SR_VWAP = {rec_weight:<4}  (was 2)             │")
    print(f"  │  CONVICTION_WEIGHT_HMM     = {hmm_adj:<4}  (reduce from 44)    │")
    print(f"  │  config.py lookback param  : keep compute_sr_position   │")
    print(f"  │                             lookback={best_lb} in main.py        │")
    print(f"  │  Weight sum check          : {total_check}/100                      │")
    if abs(comb_t_b) < 2.0:
        print(f"  │                                                         │")
        print(f"  │  ⚠ t-stat < 2 — signal not statistically significant   │")
        print(f"  │    Consider keeping weight at 2 until more data.        │")
    print(f"  └─────────────────────────────────────────────────────────┘")
    print()


if __name__ == "__main__":
    main()
