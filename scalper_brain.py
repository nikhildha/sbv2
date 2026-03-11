"""
QuickScalper Brain — Project Sentinel Execution Specialist
═══════════════════════════════════════════════════════════
Gemini-powered micro-momentum scalper that operates on 1m/5m candles.

Decision flow (NO pure indicator logic — Gemini decides):
  1. Fetch 1m OHLCV (100 candles) + L2 order book (top 10 bid/ask)
  2. Compute VWAP, RSI, StochRSI, spread, buy/sell ratio, OB imbalance
  3. Determine proposed direction from indicator bias (hints to Gemini only)
  4. Send full data context to Gemini via project_sentinel system prompt
  5. Gemini returns: EXECUTE | IGNORE, confidence (1-100), sl_price, tp_price
  6. Bot opens trade only on EXECUTE with confidence >= threshold

Key features from system prompt:
  - Slippage Check: spread > 0.05% of price → REJECT
  - Wall Detection: HMM Bullish + Ask wall within 0.2% → REJECT
  - Exhaustion Check: RSI > 85 or < 15 → look for reversal, not chase
  - VWAP: LONG only if price > VWAP; SHORT only if price < VWAP
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("QuickScalper")

# ─── Constants ────────────────────────────────────────────────────────────────

ORDERBOOK_LEVELS   = 10      # Top 10 bid/ask levels
VWAP_WINDOW_1M     = 60      # 60 × 1m = 1 hour rolling VWAP
GEMINI_CONF_MIN    = 55      # Minimum Gemini confidence to EXECUTE (1-100 scale)


# ─── System Prompt (Project Sentinel — Execution Specialist) ─────────────────

QUICKSCALPER_SYSTEM_PROMPT = """You are the QuickScalper (Execution Specialist) for "Project Sentinel."

## Role
You are an elite High-Frequency Scalping Agent. Your objective is to capture micro-bursts of momentum (0.3% - 0.7% moves) on 1-minute and 5-minute timeframes using high leverage.

## Input Data Context
- **HMM State**: Current mathematical market regime (Trend vs. Mean Reversion).
- **Order Book (L2)**: Top 10 levels of Bid/Ask depth.
- **VWAP**: Volume Weighted Average Price for intraday bias.
- **Spread**: The gap between the best bid and best ask (as % of price).
- **RSI (1m)**: Relative Strength Index on the 1-minute chart.
- **Proposed Direction**: The direction suggested by indicator analysis (LONG/SHORT) — treat as a hint only.

## The Skeptic's Decision Logic

**Slippage Check**: If the Spread is > 0.05% of the price, output decision=IGNORE. High leverage will be eaten by the spread.

**Wall Detection**: If the proposed direction is LONG (or HMM is Bullish) but there is a massive Ask Wall (large Sell orders) within 0.2% of the current price in the top_ask_levels, output decision=IGNORE.

**Exhaustion Check**: If RSI > 85, do NOT chase the long move — look for a SHORT reversal instead. If RSI < 15, do NOT chase the short move — look for a LONG reversal instead.

**VWAP Alignment**: Only go LONG if price is above VWAP. Only go SHORT if price is below VWAP. If price and proposed direction conflict with VWAP, output decision=IGNORE.

## Price & Risk Calculation
- sl_price: Hard stop, maximum 0.4% from current_price (in the adverse direction).
- tp_price: Target 0.6% to 1.0% from current_price in the favourable direction.
- Use MARKET entry for strong signal (ob_imbalance > 0.6 or < 0.4); use LIMIT entry otherwise.

## Output Requirements (STRICT JSON — no markdown, no prose)

Return ONLY this JSON object:
{
  "decision": "EXECUTE" or "IGNORE",
  "confidence": 1-100,
  "entry_type": "MARKET" or "LIMIT",
  "sl_price": <float — hard stop price>,
  "tp_price": <float — take profit price>,
  "reasoning": "<One sentence on Order Book imbalance and the key factor for your decision.>"
}

CRITICAL RULES:
- If spread_pct > 0.0005, you MUST output IGNORE. No exceptions.
- Return ONLY the JSON object. No markdown backticks, no extra text.
- sl_price and tp_price must be real numbers, not null."""


# ─── QuickScalper Brain ───────────────────────────────────────────────────────

class QuickScalperBrain:
    """
    Project Sentinel Execution Specialist.

    Workflow per coin:
      1. Fetch 1m OHLCV (100 candles)
      2. Compute VWAP (rolling 60m), RSI (14p), StochRSI (14p)
      3. Fetch L2 order book (top 10 bid/ask)
      4. Compute spread, buy/sell tape ratio, OB imbalance
      5. Determine proposed direction from indicator bias
      6. Send ALL data to Gemini → get EXECUTE/IGNORE + sl/tp prices
      7. Return result for bot to open trade
    """

    def __init__(self, exchange_client, symbol: str, leverage: int = 20, athena_engine=None, hmm_state: str = "UNKNOWN"):
        self.client      = exchange_client
        self.symbol      = symbol
        self.leverage    = min(max(leverage, 20), 50)  # Clamp 20–50x
        self.athena      = athena_engine   # AthenaEngine instance (for Gemini call)
        self.hmm_state   = hmm_state       # Passed in from main loop context (info-only)
        self._last_signal      = None
        self._last_signal_time = None
        self._signal_log       = []  # Rolling last-20 Gemini decisions

    # ─── Main Entry Point ─────────────────────────────────────────────────────

    def analyze(self) -> dict:
        """
        Run the full Gemini scalper pipeline.

        Returns
        -------
        dict with keys:
          signal:     'BUY' | 'SELL' | 'VETO'
          confidence: float 0.0-1.0  (normalized from Gemini's 1-100)
          reason:     str
          meta:       dict with indicator values + Gemini decision details
        """
        try:
            return self._run_pipeline()
        except Exception as e:
            logger.warning("⚡ QuickScalper [%s] pipeline error: %s", self.symbol, e)
            return self._veto(f"Pipeline error: {e}")

    def _run_pipeline(self) -> dict:
        # ── 1. Fetch 1m OHLCV ─────────────────────────────────────────────
        ohlcv_1m = self._fetch_ohlcv("1m", 100)
        if not ohlcv_1m or len(ohlcv_1m) < 20:
            return self._veto("Insufficient 1m data")

        close = ohlcv_1m[-1][4]   # Last close price

        # ── 2. Compute Indicators ─────────────────────────────────────────
        vwap      = self._compute_vwap(ohlcv_1m[-VWAP_WINDOW_1M:])
        rsi       = self._compute_rsi(ohlcv_1m)           # Regular RSI (14)
        stoch_rsi = self._compute_stoch_rsi(ohlcv_1m)     # StochRSI (14)
        vwap_dist_pct = (close - vwap) / vwap * 100 if vwap else 0.0

        # ── 3. Fetch L2 Order Book ────────────────────────────────────────
        orderbook = self._fetch_orderbook()
        if not orderbook or not orderbook.get("bids") or not orderbook.get("asks"):
            return self._veto("Order book unavailable")

        bids = orderbook["bids"]   # [[price, qty], ...]
        asks = orderbook["asks"]

        bid0, ask0  = bids[0][0], asks[0][0]
        mid         = (bid0 + ask0) / 2
        spread_pct  = (ask0 - bid0) / mid if mid > 0 else 0.0

        # ── 4. Buy/sell ratio from tape ───────────────────────────────────
        buy_ratio = self._fetch_buy_sell_ratio()

        # ── 5. OB imbalance ───────────────────────────────────────────────
        bid_depth    = sum(lv[1] for lv in bids[:ORDERBOOK_LEVELS])
        ask_depth    = sum(lv[1] for lv in asks[:ORDERBOOK_LEVELS])
        ob_imbalance = bid_depth / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0.5

        # ── 6. ATR estimate (0.2% proxy) ──────────────────────────────────
        atr_pct = self._compute_atr_pct(ohlcv_1m)

        # ── 7. Propose direction from indicator bias (hint only for Gemini) ─
        # This is NOT the decision — Gemini makes the decision.
        proposed = self._propose_direction(close, vwap, rsi, ob_imbalance)

        meta = {
            "vwap":         round(vwap, 6),
            "close":        round(close, 6),
            "rsi":          round(rsi, 2),
            "stoch_rsi":    round(stoch_rsi, 2),
            "spread_pct":   round(spread_pct, 6),
            "spread_bps":   round(spread_pct * 10000, 2),
            "buy_ratio":    round(buy_ratio, 3),
            "ob_imbalance": round(ob_imbalance, 3),
            "vwap_dist_pct": round(vwap_dist_pct, 4),
            "atr_pct":      round(atr_pct, 5),
            "hmm_state":    self.hmm_state,
            "proposed":     proposed,
            "leverage":     self.leverage,
        }

        # ── 8. Early veto: spread > 0.05% (Gemini will also check, but save API cost) ─
        if spread_pct > 0.0005:
            return self._veto(f"Spread {spread_pct*100:.3f}% > 0.05% limit — slippage veto (pre-Gemini)")

        # ── 9. If no Athena engine available, use indicator fallback ──────
        if not self.athena:
            return self._veto("No Gemini engine attached — skipping scalp (set athena_engine)")

        # ── 10. Call Gemini for decision ──────────────────────────────────
        scalper_ctx = {
            "symbol":            self.symbol,
            "proposed_direction": proposed,
            "hmm_state":         self.hmm_state,
            "vwap":              vwap,
            "close":             close,
            "rsi":               rsi,
            "stoch_rsi":         stoch_rsi,
            "spread_pct":        spread_pct,
            "ob_bids":           [[round(b[0], 6), round(b[1], 4)] for b in bids[:10]],
            "ob_asks":           [[round(a[0], 6), round(a[1], 4)] for a in asks[:10]],
            "buy_ratio":         buy_ratio,
            "ob_imbalance":      ob_imbalance,
            "vwap_dist_pct":     vwap_dist_pct,
            "atr_pct":           atr_pct,
        }

        gemini_result = self.athena.validate_scalper_signal(scalper_ctx)
        decision      = gemini_result.get("decision", "IGNORE")
        confidence_100 = int(gemini_result.get("confidence", 0))
        entry_type    = gemini_result.get("entry_type", "MARKET")
        sl_price      = gemini_result.get("sl_price")
        tp_price      = gemini_result.get("tp_price")
        reasoning     = gemini_result.get("reasoning", "No reasoning")

        meta.update({
            "gemini_decision": decision,
            "gemini_confidence": confidence_100,
            "entry_type": entry_type,
            "sl_price": sl_price,
            "tp_price": tp_price,
        })

        if decision != "EXECUTE" or confidence_100 < GEMINI_CONF_MIN:
            result = self._veto(f"Gemini: {decision} (conf={confidence_100}) — {reasoning}")
            result["meta"] = meta
            return result

        # Map direction to BUY/SELL
        if proposed == "LONG":
            signal = "BUY"
        elif proposed == "SHORT":
            signal = "SELL"
        else:
            return self._veto(f"Gemini EXECUTE but no clear direction (proposed={proposed})")

        confidence_norm = round(confidence_100 / 100.0, 2)

        result = {
            "signal":     signal,
            "confidence": confidence_norm,
            "reason":     reasoning,
            "meta":       meta,
        }

        # Log
        self._signal_log.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            **result
        })
        if len(self._signal_log) > 20:
            self._signal_log = self._signal_log[-20:]

        self._last_signal      = signal
        self._last_signal_time = time.time()

        logger.info(
            "⚡ QuickScalper [%s] → %s (conf=%d/100, entry=%s) — %s",
            self.symbol, signal, confidence_100, entry_type, reasoning[:80]
        )
        return result

    # ─── Direction Proposal (hint for Gemini — NOT the decision) ─────────────

    @staticmethod
    def _propose_direction(close: float, vwap: float, rsi: float, ob_imbalance: float) -> str:
        """
        Propose a direction based on indicator bias. This is passed to Gemini
        as a hint — Gemini makes the final call and may disagree.

        Rules (aligned with system prompt):
          - LONG:  price > VWAP AND rsi in 15-85 range AND bids dominant
          - SHORT: price < VWAP AND rsi in 15-85 range AND asks dominant
          - LONG (reversal): RSI < 15 (exhaustion short → look for reversal)
          - SHORT (reversal): RSI > 85 (exhaustion long → look for reversal)
        """
        vwap_long  = close > vwap
        vwap_short = close < vwap

        if rsi > 85:
            return "SHORT"   # Overbought exhaustion → reversal short
        if rsi < 15:
            return "LONG"    # Oversold exhaustion → reversal long

        if vwap_long and ob_imbalance >= 0.55:
            return "LONG"
        if vwap_short and ob_imbalance < 0.45:
            return "SHORT"

        return "NEUTRAL"   # Gemini will IGNORE this (no VWAP alignment)

    # ─── Indicator Calculations ───────────────────────────────────────────────

    @staticmethod
    def _compute_vwap(ohlcv: list) -> float:
        """VWAP = Σ(typical_price × volume) / Σ(volume)."""
        total_tpv = 0.0
        total_vol = 0.0
        for candle in ohlcv:
            _ts, o, h, l, c, v = candle[:6]
            tp = (h + l + c) / 3
            total_tpv += tp * v
            total_vol  += v
        return total_tpv / total_vol if total_vol > 0 else 0.0

    @staticmethod
    def _compute_rsi(ohlcv: list, period: int = 14) -> float:
        """Standard Wilder RSI on 1m closes. Returns 0-100."""
        closes = [c[4] for c in ohlcv]
        if len(closes) < period + 1:
            return 50.0

        gains, losses = [], []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period + 1e-10

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period + 1e-10

        rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        return round(rsi, 2)

    @staticmethod
    def _compute_stoch_rsi(ohlcv: list, rsi_period: int = 14, stoch_period: int = 14) -> float:
        """Stochastic RSI on 1m closes. Returns 0-100."""
        closes = [c[4] for c in ohlcv]
        if len(closes) < rsi_period + stoch_period:
            return 50.0

        gains, losses = [], []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))

        if len(gains) < rsi_period:
            return 50.0

        avg_gain = sum(gains[:rsi_period]) / rsi_period
        avg_loss = sum(losses[:rsi_period]) / rsi_period + 1e-10
        rsi_vals = [100.0 - 100.0 / (1.0 + avg_gain / avg_loss)]

        for i in range(rsi_period, len(gains)):
            avg_gain = (avg_gain * (rsi_period - 1) + gains[i]) / rsi_period
            avg_loss = (avg_loss * (rsi_period - 1) + losses[i]) / rsi_period + 1e-10
            rsi_vals.append(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))

        if len(rsi_vals) < stoch_period:
            return rsi_vals[-1]

        window = rsi_vals[-stoch_period:]
        lo, hi = min(window), max(window)
        if hi == lo:
            return 50.0
        return round((rsi_vals[-1] - lo) / (hi - lo) * 100, 2)

    @staticmethod
    def _compute_atr_pct(ohlcv: list, period: int = 14) -> float:
        """Average True Range as % of price for the last `period` candles."""
        if len(ohlcv) < period + 1:
            return 0.002
        trs = []
        for i in range(1, len(ohlcv)):
            h = ohlcv[i][2]
            l = ohlcv[i][3]
            pc = ohlcv[i - 1][4]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr = sum(trs[-period:]) / period
        last_close = ohlcv[-1][4]
        return atr / last_close if last_close > 0 else 0.002

    # ─── Data Fetching ────────────────────────────────────────────────────────

    def _fetch_ohlcv(self, interval: str, limit: int) -> Optional[list]:
        """Fetch OHLCV — adapts to Binance or ccxt client."""
        try:
            if hasattr(self.client, "get_klines"):
                raw = self.client.get_klines(symbol=self.symbol, interval=interval, limit=limit)
                if raw:
                    return [[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in raw]
            if hasattr(self.client, "fetch_ohlcv"):
                return self.client.fetch_ohlcv(self.symbol, interval, limit=limit)
            return None
        except Exception as e:
            logger.debug("⚡ QuickScalper OHLCV error [%s]: %s", self.symbol, e)
            return None

    def _fetch_orderbook(self) -> Optional[dict]:
        """Fetch top N bid/ask levels from L2 order book."""
        try:
            if hasattr(self.client, "get_order_book"):
                raw = self.client.get_order_book(symbol=self.symbol, limit=ORDERBOOK_LEVELS)
                if raw:
                    return {
                        "bids": [[float(p), float(q)] for p, q in raw.get("bids", [])],
                        "asks": [[float(p), float(q)] for p, q in raw.get("asks", [])],
                    }
            if hasattr(self.client, "fetch_order_book"):
                return self.client.fetch_order_book(self.symbol, ORDERBOOK_LEVELS)
            return None
        except Exception as e:
            logger.debug("⚡ QuickScalper OB error [%s]: %s", self.symbol, e)
            return None

    def _fetch_buy_sell_ratio(self) -> float:
        """Buy/sell tape ratio from last 60s of trades. Returns 0.0-1.0 buy fraction."""
        try:
            if hasattr(self.client, "get_recent_trades"):
                trades = self.client.get_recent_trades(symbol=self.symbol, limit=500)
                if trades:
                    cutoff = time.time() * 1000 - 60_000
                    recent = [t for t in trades if t.get("time", 0) > cutoff] or trades[-50:]
                    buy_vol  = sum(float(t.get("qty", 0)) for t in recent if not t.get("isBuyerMaker", True))
                    sell_vol = sum(float(t.get("qty", 0)) for t in recent if t.get("isBuyerMaker", True))
                    total = buy_vol + sell_vol
                    return buy_vol / total if total > 0 else 0.5
            return 0.5
        except Exception as e:
            logger.debug("⚡ QuickScalper tape error [%s]: %s", self.symbol, e)
            return 0.5

    # ─── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _veto(reason: str) -> dict:
        return {"signal": "VETO", "confidence": 0.0, "reason": reason, "meta": {}}

    def get_state(self) -> dict:
        """Dashboard state dict."""
        return {
            "brain_type":       "quickscalper_gemini",
            "symbol":           self.symbol,
            "leverage":         self.leverage,
            "hmm_state":        self.hmm_state,
            "last_signal":      self._last_signal,
            "last_signal_time": self._last_signal_time,
            "signal_log":       self._signal_log[-5:],
            "gemini_powered":   True,
        }
