"""
QuickScalper Brain — Micro-Level Scalping Engine
═════════════════════════════════════════════════
High-frequency scalping brain that operates on 1m/5m candles.
Uses order book L2 spread, StochRSI, VWAP, and buy/sell tape
to find exhaustion points for 0.5% micro-moves.

Key veto rules:
  - Spread widening → VETO (slippage protection)
  - Buy/sell ratio < threshold → VETO
  - StochRSI outside exhaustion zone → VETO
  - 1m HMM regime disagreement → weight down

Leverage: 20x–50x virtual (paper mode only for safety)
Target: 0.5% move with 0.25% stop loss
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("QuickScalper")

# ─── Constants ──────────────────────────────────────────────────────────────

SPREAD_VETO_BPS   = 5       # Veto if spread > 0.05% (5 basis points)
VWAP_WINDOW_1M    = 60      # 60 x 1m candles for VWAP (1 hour)
STOCH_RSI_OVERSOLD  = 20    # StochRSI < 20 → potential long
STOCH_RSI_OVERBOUGHT = 80   # StochRSI > 80 → potential short
MIN_BUY_SELL_RATIO = 0.6    # For LONG: buys must be ≥ 60% of tape volume
MAX_BUY_SELL_RATIO = 0.4    # For SHORT: buys must be ≤ 40% of tape volume
ORDERBOOK_LEVELS   = 10     # Top 10 bid/ask levels to read
WHALE_TRADE_USD    = 50_000 # Whale threshold (USD notional)


class QuickScalperBrain:
    """
    Micro-momentum scalper — reads 1m/5m candles + L2 order book.

    Workflow per coin:
      1. Fetch 1m OHLCV (100 candles) + 5m OHLCV (50 candles)
      2. Compute VWAP (1h rolling) and StochRSI(1m)
      3. Fetch L2 order book (top 10 bid/ask)
      4. Compute spread → veto if too wide
      5. Fetch recent tape (last 60s) → buy/sell ratio
      6. Combine signals → BUY / SELL / VETO
    """

    def __init__(self, exchange_client, symbol: str, leverage: int = 20):
        self.client   = exchange_client
        self.symbol   = symbol
        self.leverage = min(max(leverage, 20), 50)  # Clamp 20–50x
        self._last_signal = None
        self._last_signal_time = None
        self._signal_log = []  # Rolling last-20 signals

    # ─── Main Entry Point ────────────────────────────────────────────────────

    def analyze(self) -> dict:
        """
        Run the full scalper analysis pipeline.

        Returns
        -------
        dict with keys:
          signal:     'BUY' | 'SELL' | 'VETO'
          confidence: float 0.0-1.0
          reason:     str
          meta:       dict with indicator values
        """
        try:
            return self._run_pipeline()
        except Exception as e:
            logger.warning("⚡ QuickScalper [%s] error: %s", self.symbol, e)
            return self._veto(f"Pipeline error: {e}")

    def _run_pipeline(self) -> dict:
        # 1. Fetch 1m OHLCV (100 candles)
        ohlcv_1m = self._fetch_ohlcv("1m", 100)
        if not ohlcv_1m or len(ohlcv_1m) < 14:
            return self._veto("Insufficient 1m data")

        # 2. Compute indicators
        vwap      = self._compute_vwap(ohlcv_1m[-VWAP_WINDOW_1M:])
        stoch_rsi = self._compute_stoch_rsi(ohlcv_1m)
        close     = ohlcv_1m[-1][4]   # Last close price

        # 3. Fetch L2 order book
        orderbook = self._fetch_orderbook()
        if not orderbook:
            return self._veto("Order book unavailable")

        bid0, ask0 = orderbook["bids"][0][0], orderbook["asks"][0][0]
        mid = (bid0 + ask0) / 2
        spread_bps = ((ask0 - bid0) / mid) * 10000

        # 4. Spread veto — widen spread kills scalps
        if spread_bps > SPREAD_VETO_BPS:
            return self._veto(f"Spread {spread_bps:.1f}bps > {SPREAD_VETO_BPS}bps limit")

        # 5. Buy/sell ratio from tape (last 60s)
        buy_ratio = self._fetch_buy_sell_ratio()

        # 6. Order book imbalance
        bid_depth = sum(level[1] for level in orderbook["bids"][:ORDERBOOK_LEVELS])
        ask_depth = sum(level[1] for level in orderbook["asks"][:ORDERBOOK_LEVELS])
        ob_imbalance = bid_depth / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0.5

        meta = {
            "vwap":         round(vwap, 6),
            "close":        round(close, 6),
            "stoch_rsi":    round(stoch_rsi, 2),
            "spread_bps":   round(spread_bps, 2),
            "buy_ratio":    round(buy_ratio, 3),
            "ob_imbalance": round(ob_imbalance, 3),
            "leverage":     self.leverage,
        }

        # 7. Signal decision
        signal, confidence, reason = self._decide(
            close, vwap, stoch_rsi, buy_ratio, ob_imbalance
        )

        result = {"signal": signal, "confidence": confidence, "reason": reason, "meta": meta}

        # Log
        self._signal_log.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            **result
        })
        if len(self._signal_log) > 20:
            self._signal_log = self._signal_log[-20:]

        self._last_signal = signal
        self._last_signal_time = time.time()

        logger.info(
            "⚡ QuickScalper [%s] → %s (conf=%.2f) StochRSI=%.1f spread=%.1fbps — %s",
            self.symbol, signal, confidence, stoch_rsi, spread_bps, reason
        )
        return result

    def _decide(self, close, vwap, stoch_rsi, buy_ratio, ob_imbalance):
        """
        Signal decision tree — exhaustion-based micro-momentum.

        LONG conditions:
          - Price < VWAP (mean-reversion setup, pulled back below)
          - StochRSI < 20 (oversold 1m)
          - Buy tape ≥ 60% (buyers absorbing sells)
          - OB imbalance ≥ 55% (more bids than asks)

        SHORT conditions:
          - Price > VWAP (extended above average)
          - StochRSI > 80 (overbought 1m)
          - Buy tape ≤ 40% (sellers dominating)
          - OB imbalance < 45%
        """
        score_long  = 0.0
        score_short = 0.0

        # VWAP position
        vwap_dist_pct = (close - vwap) / vwap * 100
        if vwap_dist_pct < -0.1:
            score_long  += 0.25  # Below VWAP → potential bounce
        elif vwap_dist_pct > 0.1:
            score_short += 0.25  # Above VWAP → potential fade

        # StochRSI
        if stoch_rsi < STOCH_RSI_OVERSOLD:
            score_long  += 0.30
        elif stoch_rsi > STOCH_RSI_OVERBOUGHT:
            score_short += 0.30
        else:
            # Neutral zone — no strong signal
            return "VETO", 0.0, f"StochRSI {stoch_rsi:.1f} in neutral zone (20-80)"

        # Buy/sell ratio
        if buy_ratio >= MIN_BUY_SELL_RATIO:
            score_long  += 0.25
        elif buy_ratio <= MAX_BUY_SELL_RATIO:
            score_short += 0.25

        # Order book imbalance
        if ob_imbalance >= 0.55:
            score_long  += 0.20
        elif ob_imbalance < 0.45:
            score_short += 0.20

        # Decide
        if score_long >= 0.60:
            return "BUY", round(score_long, 2), (
                f"LONG setup: VWAP dist={vwap_dist_pct:.2f}% "
                f"StochRSI={stoch_rsi:.0f} buys={buy_ratio:.1%} OB={ob_imbalance:.1%}"
            )
        elif score_short >= 0.60:
            return "SELL", round(score_short, 2), (
                f"SHORT setup: VWAP dist={vwap_dist_pct:.2f}% "
                f"StochRSI={stoch_rsi:.0f} buys={buy_ratio:.1%} OB={ob_imbalance:.1%}"
            )
        else:
            return "VETO", 0.0, (
                f"Weak setup: long={score_long:.2f} short={score_short:.2f} — no exhaustion confirmed"
            )

    # ─── Indicator Calculations ──────────────────────────────────────────────

    @staticmethod
    def _compute_vwap(ohlcv: list) -> float:
        """VWAP = Σ(typical_price × volume) / Σ(volume)."""
        total_tp_vol = 0.0
        total_vol    = 0.0
        for candle in ohlcv:
            _ts, o, h, l, c, v = candle[:6]
            tp = (h + l + c) / 3
            total_tp_vol += tp * v
            total_vol    += v
        return total_tp_vol / total_vol if total_vol > 0 else 0.0

    @staticmethod
    def _compute_stoch_rsi(ohlcv: list, rsi_period: int = 14, stoch_period: int = 14) -> float:
        """
        Stochastic RSI on close prices.
        Returns value in 0–100 range.
        """
        closes = [c[4] for c in ohlcv]
        if len(closes) < rsi_period + stoch_period:
            return 50.0   # Neutral if insufficient data

        # RSI
        gains, losses = [], []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            gains.append(max(delta, 0))
            losses.append(max(-delta, 0))

        if len(gains) < rsi_period:
            return 50.0

        avg_gain = sum(gains[:rsi_period]) / rsi_period
        avg_loss = sum(losses[:rsi_period]) / rsi_period + 1e-10
        rsi_values = [100 - 100 / (1 + avg_gain / avg_loss)]

        for i in range(rsi_period, len(gains)):
            avg_gain = (avg_gain * (rsi_period - 1) + gains[i]) / rsi_period
            avg_loss = (avg_loss * (rsi_period - 1) + losses[i]) / rsi_period + 1e-10
            rsi_values.append(100 - 100 / (1 + avg_gain / avg_loss))

        if len(rsi_values) < stoch_period:
            return rsi_values[-1]

        rsi_window = rsi_values[-stoch_period:]
        rsi_low    = min(rsi_window)
        rsi_high   = max(rsi_window)
        if rsi_high == rsi_low:
            return 50.0
        stoch_rsi = (rsi_values[-1] - rsi_low) / (rsi_high - rsi_low) * 100
        return round(stoch_rsi, 2)

    # ─── Data Fetching (adapts to existing exchange clients) ─────────────────

    def _fetch_ohlcv(self, interval: str, limit: int) -> Optional[list]:
        """Fetch OHLCV from exchange client. Returns list of [ts,o,h,l,c,v]."""
        try:
            # Try Binance futures client interface
            if hasattr(self.client, 'get_klines'):
                raw = self.client.get_klines(
                    symbol=self.symbol, interval=interval, limit=limit
                )
                if raw:
                    return [[
                        r[0], float(r[1]), float(r[2]),
                        float(r[3]), float(r[4]), float(r[5])
                    ] for r in raw]
            # Try ccxt-compatible interface
            if hasattr(self.client, 'fetch_ohlcv'):
                return self.client.fetch_ohlcv(self.symbol, interval, limit=limit)
            return None
        except Exception as e:
            logger.debug("⚡ QuickScalper OHLCV fetch error: %s", e)
            return None

    def _fetch_orderbook(self) -> Optional[dict]:
        """Fetch L2 order book top N levels."""
        try:
            if hasattr(self.client, 'get_order_book'):
                raw = self.client.get_order_book(symbol=self.symbol, limit=ORDERBOOK_LEVELS)
                if raw:
                    return {
                        "bids": [[float(p), float(q)] for p, q in raw.get("bids", [])],
                        "asks": [[float(p), float(q)] for p, q in raw.get("asks", [])],
                    }
            if hasattr(self.client, 'fetch_order_book'):
                return self.client.fetch_order_book(self.symbol, ORDERBOOK_LEVELS)
            return None
        except Exception as e:
            logger.debug("⚡ QuickScalper OB fetch error: %s", e)
            return None

    def _fetch_buy_sell_ratio(self) -> float:
        """
        Get buy/sell tape ratio from last 60s of recent trades.
        Returns fraction of volume that was buy-side (0.0–1.0).
        """
        try:
            if hasattr(self.client, 'get_recent_trades'):
                trades = self.client.get_recent_trades(symbol=self.symbol, limit=500)
                if trades:
                    cutoff = time.time() * 1000 - 60_000  # Last 60 seconds
                    recent = [t for t in trades if t.get("time", 0) > cutoff]
                    if not recent:
                        recent = trades[-50:]  # Fallback: last 50 trades
                    buy_vol  = sum(float(t.get("qty", 0)) for t in recent if not t.get("isBuyerMaker", True))
                    sell_vol = sum(float(t.get("qty", 0)) for t in recent if t.get("isBuyerMaker", True))
                    total = buy_vol + sell_vol
                    return buy_vol / total if total > 0 else 0.5
            return 0.5  # Neutral if unavailable
        except Exception as e:
            logger.debug("⚡ QuickScalper tape fetch error: %s", e)
            return 0.5

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _veto(reason: str) -> dict:
        return {"signal": "VETO", "confidence": 0.0, "reason": reason, "meta": {}}

    def get_state(self) -> dict:
        """Dashboard state dict."""
        return {
            "brain_type": "quickscalper",
            "symbol": self.symbol,
            "leverage": self.leverage,
            "last_signal": self._last_signal,
            "last_signal_time": self._last_signal_time,
            "signal_log": self._signal_log[-5:],
        }


# ─── LLM System Prompt ───────────────────────────────────────────────────────

QUICKSCALPER_SYSTEM_PROMPT = """You are a High-Frequency Scalper AI operating on 1-minute crypto futures data.

## Your Role
You are a **Micro-Momentum Filter**. You do NOT look at news, macro trends, or fundamentals.
You ONLY look for 1-minute exhaustion signals and rapid RSI reversals.

## Your Goal
Find an imminent **0.5% price move** backed by exhaustion evidence.
Your holding period is 1–5 minutes. Act fast or VETO.

## Decision Rules
1. If the spread is widening → VETO immediately (slippage will kill the trade)
2. If StochRSI is between 20–80 → VETO (no exhaustion, wait for extremes)
3. If buy/sell ratio contradicts the proposed direction → VETO
4. If price is not at VWAP reversion point → downgrade confidence

## Input Format
You will receive a JSON with:
- spread_bps: current bid/ask spread in basis points
- stoch_rsi: 1m StochRSI (0–100)
- buy_ratio: fraction of last-60s volume that was buy-side
- ob_imbalance: fraction of L2 depth on bid side (top 10 levels)
- vwap_dist_pct: % distance of price from 1h VWAP
- proposed_signal: BUY or SELL
- hmm_1m_regime: HMM model's 1m regime

## Output Format
Return ONLY a JSON object:
{
  "action": "EXECUTE" | "REDUCE_SIZE" | "VETO",
  "adjusted_confidence": 0.0-1.0,
  "reasoning": "One sentence max.",
  "risk_flags": ["flag1"]
}

CRITICAL: If spread_bps > 5, you MUST output VETO. No exceptions."""
