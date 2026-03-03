"""
Project Regime-Master — Order Flow Engine (v2 — Multi-Exchange + Order Blocks)
Aggregates publicly available market microstructure data from Binance, OKX and
Bybit to produce a unified order flow signal.

Sources (all free, no API key needed):
  1. L2 Order Book  — Aggregated depth from Binance + OKX + Bybit
  2. Taker Flow     — Buy/sell volume already embedded in OHLCV klines
  3. L/S Ratio      — Binance futures global long/short account ratio
  4. Cumulative Delta — Net buy − sell from recent aggTrades (multi-exchange)
  5. Order Blocks   — Smart-money zones detected from 1h candles

Output: OrderFlowSignal with a single composite score in [-1, +1]
  • Positive → buy pressure dominates (supports LONG)
  • Negative → sell pressure dominates (supports SHORT)
  • Near-zero → market is balanced / uncertain

Integration:
  • compute_conviction_score() reads orderflow_score (8th factor, 10 pts)
  • main.py calls get_engine().get_signal(symbol, df_15m) each analysis cycle
"""
from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

import config

logger = logging.getLogger("OrderFlowEngine")

# ─── Exchange API endpoints ──────────────────────────────────────────────────
_BINANCE_SPOT    = "https://api.binance.com/api/v3"
_BINANCE_FUTURES = "https://fapi.binance.com/fapi/v1"
_OKX_BASE        = "https://www.okx.com/api/v5"
_BYBIT_BASE      = "https://api.bybit.com/v5"


# ─── Data models ─────────────────────────────────────────────────────────────

@dataclass
class WallLevel:
    """A price level with an unusually large resting order."""
    price: float
    size_usd: float     # notional at this level
    side: str           # "bid" or "ask"
    multiple: float     # how many × the average level size
    exchange: str = ""  # which exchange(s) contributed


@dataclass
class OrderBlock:
    """A smart-money accumulation/distribution zone detected from candles."""
    type: str           # "bullish" or "bearish"
    zone_low: float     # Bottom of the OB zone
    zone_high: float    # Top of the OB zone
    volume: float       # Volume at this zone (USD)
    strength: float     # 0-1 score based on volume + reaction strength
    age_hours: float    # How old is this OB
    tested: bool        # Has price returned to this zone?

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "zone_low": round(self.zone_low, 2),
            "zone_high": round(self.zone_high, 2),
            "volume": round(self.volume, 0),
            "strength": round(self.strength, 3),
            "age_hours": round(self.age_hours, 1),
            "tested": self.tested,
        }


@dataclass
class OrderFlowSignal:
    """Composite order-flow signal for one coin at a point in time."""
    symbol: str
    score: float                        # -1 to +1 composite
    book_imbalance: float               # -1 to +1 (bid depth vs ask depth)
    taker_buy_ratio: float              # 0 to 1 (1 = all buys)
    cumulative_delta: float             # -1 to +1 (recent net buy flow)
    ls_ratio: float                     # > 1 = more longs; < 1 = more shorts
    bid_walls: List[WallLevel] = field(default_factory=list)
    ask_walls: List[WallLevel] = field(default_factory=list)
    order_blocks: List[OrderBlock] = field(default_factory=list)
    nearest_bullish_ob: Optional[float] = None
    nearest_bearish_ob: Optional[float] = None
    exchange_count: int = 1             # How many exchanges contributed data
    aggregated_bid_usd: float = 0.0     # Total bid depth across all exchanges
    aggregated_ask_usd: float = 0.0     # Total ask depth across all exchanges
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    note: str = ""

    @property
    def nearest_bid_wall(self) -> Optional[float]:
        return max((w.price for w in self.bid_walls), default=None)

    @property
    def nearest_ask_wall(self) -> Optional[float]:
        return min((w.price for w in self.ask_walls), default=None)


# ─── Engine ──────────────────────────────────────────────────────────────────

class OrderFlowEngine:
    """
    Fetches and combines microstructure signals into a single conviction modifier.

    Cache behaviour:
      • Each (symbol) result is cached for ORDERFLOW_CACHE_SECONDS
      • Stale cache is returned on network failure rather than crashing
    """

    def __init__(self):
        self._cache: Dict[str, Tuple[float, OrderFlowSignal]] = {}
        self._executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="orderflow")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_signal(self, symbol: str, df_15m=None) -> Optional[OrderFlowSignal]:
        """
        Return an OrderFlowSignal for *symbol*.

        Parameters
        ----------
        symbol  : str, e.g. "BTCUSDT"
        df_15m  : optional pandas DataFrame of 15-min OHLCV klines.
                  When provided, taker buy/sell volumes are extracted from it
                  (avoids an extra REST call).

        Returns None only if ALL sub-fetches fail.
        """
        if not config.ORDERFLOW_ENABLED:
            return None

        cached = self._cache.get(symbol)
        if cached:
            ts, sig = cached
            if time.time() - ts < config.ORDERFLOW_CACHE_SECONDS:
                return sig

        try:
            sig = self._compute(symbol, df_15m)
        except Exception as e:
            logger.warning("[OrderFlow] compute failed for %s: %s", symbol, e)
            if cached:
                return cached[1]
            return None

        self._cache[symbol] = (time.time(), sig)
        return sig

    # ── Core compute ─────────────────────────────────────────────────────────

    def _compute(self, symbol: str, df_15m) -> OrderFlowSignal:
        """Fetch all sub-signals and combine into one score."""

        # 1. Order book imbalance + walls (multi-exchange)
        book_result = self._fetch_aggregated_book(symbol)
        book_imbalance = book_result["imbalance"]
        bid_walls = book_result["bid_walls"]
        ask_walls = book_result["ask_walls"]
        exchange_count = book_result["exchange_count"]
        agg_bid_usd = book_result["total_bid_usd"]
        agg_ask_usd = book_result["total_ask_usd"]

        # 2. Taker buy ratio — from klines df if available, otherwise REST
        taker_buy_ratio = self._get_taker_ratio(symbol, df_15m)

        # 3. Cumulative delta from recent aggTrades (multi-exchange)
        cum_delta = self._fetch_aggregated_cum_delta(symbol)

        # 4. Long/short ratio from Binance futures
        ls_ratio = self._fetch_ls_ratio(symbol) if config.ORDERFLOW_LS_ENABLED else 1.0

        # 5. Order block detection
        order_blocks = []
        nearest_bull_ob = None
        nearest_bear_ob = None
        ob_score_adj = 0.0

        if getattr(config, "ORDERFLOW_OB_DETECTION", False):
            order_blocks = self._detect_order_blocks(symbol)
            if order_blocks:
                # Find nearest OB zones relative to current mid price
                mid_price = (agg_bid_usd + agg_ask_usd) / 2 if (agg_bid_usd + agg_ask_usd) > 0 else 0
                # Use the top bid price as proxy for current price
                if bid_walls:
                    current_price = bid_walls[0].price
                else:
                    current_price = self._get_current_price(symbol)

                if current_price > 0:
                    proximity_pct = getattr(config, "ORDERFLOW_OB_PROXIMITY_PCT", 0.005)
                    for ob in order_blocks:
                        zone_mid = (ob.zone_low + ob.zone_high) / 2
                        dist_pct = abs(current_price - zone_mid) / current_price

                        if ob.type == "bullish":
                            if nearest_bull_ob is None or dist_pct < abs(current_price - nearest_bull_ob) / current_price:
                                nearest_bull_ob = zone_mid
                            if dist_pct <= proximity_pct and current_price >= ob.zone_low:
                                ob_score_adj += 0.1 * ob.strength

                        elif ob.type == "bearish":
                            if nearest_bear_ob is None or dist_pct < abs(current_price - nearest_bear_ob) / current_price:
                                nearest_bear_ob = zone_mid
                            if dist_pct <= proximity_pct and current_price <= ob.zone_high:
                                ob_score_adj -= 0.1 * ob.strength

        # ── Combine sub-scores ───────────────────────────────────────────────
        taker_score = 2.0 * (taker_buy_ratio - 0.5)
        ls_score    = _clamp((ls_ratio - 1.0) / 0.5)

        composite = (
            0.35 * book_imbalance
            + 0.30 * taker_score
            + 0.25 * cum_delta
            + 0.10 * ls_score
        )
        # Apply order block adjustment
        composite += ob_score_adj
        composite = _clamp(composite)

        notes = []
        if exchange_count > 1:
            notes.append(f"aggregated from {exchange_count} exchanges")
        if bid_walls:
            notes.append(f"{len(bid_walls)} bid wall(s) near ${bid_walls[0].price:,.0f}")
        if ask_walls:
            notes.append(f"{len(ask_walls)} ask wall(s) near ${ask_walls[0].price:,.0f}")
        if order_blocks:
            bull_obs = [ob for ob in order_blocks if ob.type == "bullish"]
            bear_obs = [ob for ob in order_blocks if ob.type == "bearish"]
            if bull_obs:
                notes.append(f"{len(bull_obs)} bullish OB zone(s)")
            if bear_obs:
                notes.append(f"{len(bear_obs)} bearish OB zone(s)")

        return OrderFlowSignal(
            symbol=symbol,
            score=composite,
            book_imbalance=book_imbalance,
            taker_buy_ratio=taker_buy_ratio,
            cumulative_delta=cum_delta,
            ls_ratio=ls_ratio,
            bid_walls=bid_walls,
            ask_walls=ask_walls,
            order_blocks=order_blocks,
            nearest_bullish_ob=nearest_bull_ob,
            nearest_bearish_ob=nearest_bear_ob,
            exchange_count=exchange_count,
            aggregated_bid_usd=agg_bid_usd,
            aggregated_ask_usd=agg_ask_usd,
            note="; ".join(notes) if notes else "",
        )

    # ══════════════════════════════════════════════════════════════════════════
    #  1. AGGREGATED ORDER BOOK
    # ══════════════════════════════════════════════════════════════════════════

    def _fetch_aggregated_book(self, symbol: str) -> dict:
        """
        Fetch L2 order book from Binance + OKX + Bybit in parallel,
        merge into a unified depth, and detect walls.
        """
        multi = getattr(config, "ORDERFLOW_MULTI_EXCHANGE", False)
        limit = config.ORDERFLOW_DEPTH_LEVELS * 5

        results = {}  # exchange_name → (bids, asks)

        if multi:
            futures = {}
            futures["binance"] = self._executor.submit(self._fetch_binance_book, symbol, limit)
            futures["okx"]     = self._executor.submit(self._fetch_okx_book, symbol, limit)
            futures["bybit"]   = self._executor.submit(self._fetch_bybit_book, symbol, limit)

            for name, fut in futures.items():
                try:
                    bids, asks = fut.result(timeout=10)
                    if bids or asks:
                        results[name] = (bids, asks)
                except Exception as e:
                    logger.debug("[OrderFlow] %s book fetch failed: %s", name, e)
        else:
            bids, asks = self._fetch_binance_book(symbol, limit)
            if bids or asks:
                results["binance"] = (bids, asks)

        if not results:
            return {"imbalance": 0.0, "bid_walls": [], "ask_walls": [],
                    "exchange_count": 0, "total_bid_usd": 0.0, "total_ask_usd": 0.0}

        # Merge all bids and asks across exchanges
        all_bids: List[Tuple[float, float, str]] = []  # (price, usd, exchange)
        all_asks: List[Tuple[float, float, str]] = []

        for exch_name, (bids, asks) in results.items():
            for price, qty in bids[:config.ORDERFLOW_DEPTH_LEVELS]:
                all_bids.append((price, price * qty, exch_name))
            for price, qty in asks[:config.ORDERFLOW_DEPTH_LEVELS]:
                all_asks.append((price, price * qty, exch_name))

        # Sort bids descending (best bid first), asks ascending (best ask first)
        all_bids.sort(key=lambda x: x[0], reverse=True)
        all_asks.sort(key=lambda x: x[0])

        total_bid_usd = sum(usd for _, usd, _ in all_bids)
        total_ask_usd = sum(usd for _, usd, _ in all_asks)
        total = total_bid_usd + total_ask_usd
        imbalance = (total_bid_usd - total_ask_usd) / total if total > 0 else 0.0

        # Wall detection on aggregated levels
        threshold = config.ORDERFLOW_WALL_THRESHOLD
        large_order = config.ORDERFLOW_LARGE_ORDER_USD

        avg_bid = total_bid_usd / len(all_bids) if all_bids else 1
        avg_ask = total_ask_usd / len(all_asks) if all_asks else 1

        bid_walls: List[WallLevel] = []
        for price, usd, exch in all_bids:
            mult = usd / avg_bid if avg_bid > 0 else 0
            if mult >= threshold and usd >= large_order:
                bid_walls.append(WallLevel(price=price, size_usd=usd, side="bid",
                                           multiple=mult, exchange=exch))
        bid_walls.sort(key=lambda w: w.price, reverse=True)

        ask_walls: List[WallLevel] = []
        for price, usd, exch in all_asks:
            mult = usd / avg_ask if avg_ask > 0 else 0
            if mult >= threshold and usd >= large_order:
                ask_walls.append(WallLevel(price=price, size_usd=usd, side="ask",
                                           multiple=mult, exchange=exch))
        ask_walls.sort(key=lambda w: w.price)

        exchange_count = len(results)
        logger.debug(
            "[OrderFlow] %s aggregated book: exchanges=%d imbalance=%.3f "
            "bid_usd=%.0f ask_usd=%.0f walls(b=%d a=%d)",
            symbol, exchange_count, imbalance, total_bid_usd, total_ask_usd,
            len(bid_walls), len(ask_walls),
        )

        return {
            "imbalance": _clamp(imbalance),
            "bid_walls": bid_walls,
            "ask_walls": ask_walls,
            "exchange_count": exchange_count,
            "total_bid_usd": total_bid_usd,
            "total_ask_usd": total_ask_usd,
        }

    # ── Per-exchange book fetchers ───────────────────────────────────────────

    def _fetch_binance_book(self, symbol: str, limit: int) -> Tuple[List, List]:
        """Fetch Binance spot depth. Returns (bids, asks) as [(price, qty), ...]."""
        try:
            resp = requests.get(
                f"{_BINANCE_SPOT}/depth",
                params={"symbol": symbol, "limit": limit},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            bids = [(float(p), float(q)) for p, q in data.get("bids", [])]
            asks = [(float(p), float(q)) for p, q in data.get("asks", [])]
            return bids, asks
        except Exception as e:
            logger.debug("[OrderFlow] Binance book fetch failed for %s: %s", symbol, e)
            return [], []

    def _fetch_okx_book(self, symbol: str, limit: int) -> Tuple[List, List]:
        """Fetch OKX depth. Converts BTCUSDT → BTC-USDT instrument ID."""
        try:
            # Convert Binance-style symbol to OKX instrument ID
            # BTCUSDT → BTC-USDT, ETHUSDT → ETH-USDT
            base = symbol.replace("USDT", "")
            inst_id = f"{base}-USDT"
            sz = min(limit, 400)  # OKX max is 400

            resp = requests.get(
                f"{_OKX_BASE}/market/books",
                params={"instId": inst_id, "sz": sz},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "0" or not data.get("data"):
                return [], []

            book = data["data"][0]
            # OKX format: [[price, qty, liquidation_orders, num_orders], ...]
            bids = [(float(level[0]), float(level[1])) for level in book.get("bids", [])]
            asks = [(float(level[0]), float(level[1])) for level in book.get("asks", [])]
            return bids, asks
        except Exception as e:
            logger.debug("[OrderFlow] OKX book fetch failed for %s: %s", symbol, e)
            return [], []

    def _fetch_bybit_book(self, symbol: str, limit: int) -> Tuple[List, List]:
        """Fetch Bybit depth. Uses spot category."""
        try:
            sz = min(limit, 200)  # Bybit max is 200

            resp = requests.get(
                f"{_BYBIT_BASE}/market/orderbook",
                params={"category": "spot", "symbol": symbol, "limit": sz},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("retCode") != 0 or not data.get("result"):
                return [], []

            result = data["result"]
            # Bybit format: {"b": [[price, qty], ...], "a": [[price, qty], ...]}
            bids = [(float(p), float(q)) for p, q in result.get("b", [])]
            asks = [(float(p), float(q)) for p, q in result.get("a", [])]
            return bids, asks
        except Exception as e:
            logger.debug("[OrderFlow] Bybit book fetch failed for %s: %s", symbol, e)
            return [], []

    # ══════════════════════════════════════════════════════════════════════════
    #  2. TAKER BUY RATIO
    # ══════════════════════════════════════════════════════════════════════════

    def _get_taker_ratio(self, symbol: str, df_15m) -> float:
        """
        Taker buy ratio = taker_buy_volume / total_volume over recent bars.
        """
        try:
            if df_15m is not None and len(df_15m) >= config.ORDERFLOW_LOOKBACK_BARS:
                if "taker_buy_vol" in df_15m.columns:
                    n = config.ORDERFLOW_LOOKBACK_BARS
                    buy_vol  = df_15m["taker_buy_vol"].iloc[-n:].sum()
                    tot_vol  = df_15m["volume"].iloc[-n:].sum()
                    if tot_vol > 0:
                        return float(buy_vol / tot_vol)
        except Exception:
            pass

        # Fallback: fetch klines from Binance REST
        try:
            resp = requests.get(
                f"{_BINANCE_SPOT}/klines",
                params={
                    "symbol":   symbol,
                    "interval": "15m",
                    "limit":    config.ORDERFLOW_LOOKBACK_BARS,
                },
                timeout=8,
            )
            resp.raise_for_status()
            rows = resp.json()
            buy_vol = sum(float(r[9]) for r in rows)
            tot_vol = sum(float(r[5]) for r in rows)
            return float(buy_vol / tot_vol) if tot_vol > 0 else 0.5
        except Exception as e:
            logger.debug("[OrderFlow] taker ratio fetch failed for %s: %s", symbol, e)
            return 0.5

    # ══════════════════════════════════════════════════════════════════════════
    #  3. AGGREGATED CUMULATIVE DELTA
    # ══════════════════════════════════════════════════════════════════════════

    def _fetch_aggregated_cum_delta(self, symbol: str) -> float:
        """
        Cumulative delta aggregated across multiple exchanges.
        buy_vol - sell_vol / total, range -1..+1.
        """
        multi = getattr(config, "ORDERFLOW_MULTI_EXCHANGE", False)
        total_buy = 0.0
        total_sell = 0.0
        exchanges_ok = 0

        if multi:
            futures = {
                "binance": self._executor.submit(self._fetch_binance_cum_delta, symbol),
                "okx":     self._executor.submit(self._fetch_okx_cum_delta, symbol),
                "bybit":   self._executor.submit(self._fetch_bybit_cum_delta, symbol),
            }
            for name, fut in futures.items():
                try:
                    buy, sell = fut.result(timeout=10)
                    if buy > 0 or sell > 0:
                        total_buy += buy
                        total_sell += sell
                        exchanges_ok += 1
                except Exception as e:
                    logger.debug("[OrderFlow] %s cum delta failed: %s", name, e)
        else:
            buy, sell = self._fetch_binance_cum_delta(symbol)
            total_buy += buy
            total_sell += sell
            if buy > 0 or sell > 0:
                exchanges_ok += 1

        total = total_buy + total_sell
        delta = (total_buy - total_sell) / total if total > 0 else 0.0

        if exchanges_ok > 1:
            logger.debug("[OrderFlow] %s aggregated cumDelta=%.3f from %d exchanges "
                        "(buy=%.0f sell=%.0f)", symbol, delta, exchanges_ok,
                        total_buy, total_sell)

        return _clamp(delta)

    # ── Per-exchange cumulative delta fetchers ───────────────────────────────

    def _fetch_binance_cum_delta(self, symbol: str) -> Tuple[float, float]:
        """Returns (buy_vol_usd, sell_vol_usd) from Binance aggTrades."""
        try:
            resp = requests.get(
                f"{_BINANCE_SPOT}/aggTrades",
                params={"symbol": symbol, "limit": 500},
                timeout=8,
            )
            resp.raise_for_status()
            trades = resp.json()
        except Exception as e:
            logger.debug("[OrderFlow] Binance aggTrade failed for %s: %s", symbol, e)
            return 0.0, 0.0

        buy_vol = sell_vol = 0.0
        for t in trades:
            qty   = float(t.get("q", 0))
            price = float(t.get("p", 0))
            usd   = qty * price
            if t.get("m"):  # m = True → taker is SELLING
                sell_vol += usd
            else:
                buy_vol  += usd
        return buy_vol, sell_vol

    def _fetch_okx_cum_delta(self, symbol: str) -> Tuple[float, float]:
        """Returns (buy_vol_usd, sell_vol_usd) from OKX trades."""
        try:
            base = symbol.replace("USDT", "")
            inst_id = f"{base}-USDT"

            resp = requests.get(
                f"{_OKX_BASE}/market/trades",
                params={"instId": inst_id, "limit": 500},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "0" or not data.get("data"):
                return 0.0, 0.0

            buy_vol = sell_vol = 0.0
            for t in data["data"]:
                price = float(t.get("px", 0))
                qty   = float(t.get("sz", 0))
                usd   = price * qty
                side  = t.get("side", "")
                if side == "buy":
                    buy_vol += usd
                else:
                    sell_vol += usd
            return buy_vol, sell_vol
        except Exception as e:
            logger.debug("[OrderFlow] OKX trades failed for %s: %s", symbol, e)
            return 0.0, 0.0

    def _fetch_bybit_cum_delta(self, symbol: str) -> Tuple[float, float]:
        """Returns (buy_vol_usd, sell_vol_usd) from Bybit recent trades."""
        try:
            resp = requests.get(
                f"{_BYBIT_BASE}/market/recent-trade",
                params={"category": "spot", "symbol": symbol, "limit": 500},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("retCode") != 0 or not data.get("result"):
                return 0.0, 0.0

            buy_vol = sell_vol = 0.0
            for t in data["result"].get("list", []):
                price = float(t.get("price", 0))
                qty   = float(t.get("size", 0))
                usd   = price * qty
                side  = t.get("side", "")
                if side == "Buy":
                    buy_vol += usd
                else:
                    sell_vol += usd
            return buy_vol, sell_vol
        except Exception as e:
            logger.debug("[OrderFlow] Bybit trades failed for %s: %s", symbol, e)
            return 0.0, 0.0

    # ══════════════════════════════════════════════════════════════════════════
    #  4. LONG/SHORT RATIO (Binance only — most reliable)
    # ══════════════════════════════════════════════════════════════════════════

    def _fetch_ls_ratio(self, symbol: str) -> float:
        """Binance futures global long/short account ratio. Returns 1.0 if fails."""
        try:
            resp = requests.get(
                "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
                params={"symbol": symbol, "period": "15m", "limit": 1},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                return float(data[0].get("longShortRatio", 1.0))
        except Exception as e:
            logger.debug("[OrderFlow] L/S ratio fetch failed for %s: %s", symbol, e)
        return 1.0

    # ══════════════════════════════════════════════════════════════════════════
    #  5. ORDER BLOCK DETECTION
    # ══════════════════════════════════════════════════════════════════════════

    def _detect_order_blocks(self, symbol: str) -> List[OrderBlock]:
        """
        Detect order blocks from 1h candles.

        Bullish OB: Last bearish candle before a strong bullish impulse.
                    Zone = [low, close] of that candle.
                    (Institutions bought into selling pressure.)

        Bearish OB: Last bullish candle before a strong bearish impulse.
                    Zone = [open, high] of that candle.
                    (Institutions sold into buying pressure.)
        """
        lookback = getattr(config, "ORDERFLOW_OB_LOOKBACK_CANDLES", 100)
        sigma_threshold = getattr(config, "ORDERFLOW_OB_IMPULSE_SIGMA", 1.5)

        try:
            resp = requests.get(
                f"{_BINANCE_SPOT}/klines",
                params={"symbol": symbol, "interval": "1h", "limit": lookback},
                timeout=10,
            )
            resp.raise_for_status()
            candles = resp.json()
        except Exception as e:
            logger.debug("[OrderFlow] OB candle fetch failed for %s: %s", symbol, e)
            return []

        if len(candles) < 20:
            return []

        # Parse candles: [timestamp, open, high, low, close, volume, ...]
        parsed = []
        for c in candles:
            parsed.append({
                "ts": float(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
                "body": float(c[4]) - float(c[1]),  # close - open
            })

        # Compute return standard deviation for impulse detection
        returns = []
        for i in range(1, len(parsed)):
            prev_close = parsed[i - 1]["close"]
            if prev_close > 0:
                returns.append((parsed[i]["close"] - prev_close) / prev_close)

        if not returns:
            return []

        avg_ret = sum(returns) / len(returns)
        stddev = math.sqrt(sum((r - avg_ret) ** 2 for r in returns) / len(returns))
        if stddev == 0:
            return []

        current_price = parsed[-1]["close"]
        current_ts = time.time() * 1000
        order_blocks: List[OrderBlock] = []

        # Scan for OB patterns
        for i in range(2, len(parsed) - 1):
            candle = parsed[i]
            next_candle = parsed[i + 1]
            prev_close = parsed[i - 1]["close"]

            if prev_close == 0:
                continue

            # Impulse move = return of the candle AFTER our candidate OB candle
            impulse_ret = (next_candle["close"] - candle["close"]) / candle["close"] if candle["close"] > 0 else 0

            # Age of this OB
            age_hours = (current_ts - candle["ts"]) / 3_600_000

            # BULLISH OB: bearish candle (close < open) followed by strong up-move
            if candle["body"] < 0 and impulse_ret > sigma_threshold * stddev:
                zone_low = candle["low"]
                zone_high = candle["close"]  # close is lower for bearish candle
                if zone_high < zone_low:
                    zone_low, zone_high = zone_high, zone_low

                volume_usd = candle["volume"] * candle["close"]

                # Check if price has tested (returned to) this zone
                tested = False
                for j in range(i + 2, len(parsed)):
                    if parsed[j]["low"] <= zone_high:
                        tested = True
                        break

                strength = min(1.0, abs(impulse_ret) / (sigma_threshold * stddev * 2))
                # Boost strength by volume
                avg_vol = sum(c["volume"] for c in parsed) / len(parsed)
                if avg_vol > 0:
                    vol_mult = candle["volume"] / avg_vol
                    strength = min(1.0, strength * (0.5 + 0.5 * min(vol_mult, 3) / 3))

                order_blocks.append(OrderBlock(
                    type="bullish",
                    zone_low=zone_low,
                    zone_high=zone_high,
                    volume=volume_usd,
                    strength=strength,
                    age_hours=age_hours,
                    tested=tested,
                ))

            # BEARISH OB: bullish candle (close > open) followed by strong down-move
            elif candle["body"] > 0 and impulse_ret < -sigma_threshold * stddev:
                zone_low = candle["open"]
                zone_high = candle["high"]

                volume_usd = candle["volume"] * candle["close"]

                tested = False
                for j in range(i + 2, len(parsed)):
                    if parsed[j]["high"] >= zone_low:
                        tested = True
                        break

                strength = min(1.0, abs(impulse_ret) / (sigma_threshold * stddev * 2))
                avg_vol = sum(c["volume"] for c in parsed) / len(parsed)
                if avg_vol > 0:
                    vol_mult = candle["volume"] / avg_vol
                    strength = min(1.0, strength * (0.5 + 0.5 * min(vol_mult, 3) / 3))

                order_blocks.append(OrderBlock(
                    type="bearish",
                    zone_low=zone_low,
                    zone_high=zone_high,
                    volume=volume_usd,
                    strength=strength,
                    age_hours=age_hours,
                    tested=tested,
                ))

        # Sort by strength descending, keep top 3 of each type
        bullish_obs = sorted([ob for ob in order_blocks if ob.type == "bullish"],
                            key=lambda x: x.strength, reverse=True)[:3]
        bearish_obs = sorted([ob for ob in order_blocks if ob.type == "bearish"],
                            key=lambda x: x.strength, reverse=True)[:3]

        result = bullish_obs + bearish_obs
        if result:
            logger.debug("[OrderFlow] %s detected %d bullish + %d bearish order blocks",
                        symbol, len(bullish_obs), len(bearish_obs))
        return result

    # ── Utility ──────────────────────────────────────────────────────────────

    def _get_current_price(self, symbol: str) -> float:
        """Quick price fetch for OB proximity check."""
        try:
            resp = requests.get(
                f"{_BINANCE_SPOT}/ticker/price",
                params={"symbol": symbol},
                timeout=5,
            )
            resp.raise_for_status()
            return float(resp.json().get("price", 0))
        except Exception:
            return 0.0


# ─── Singleton access ─────────────────────────────────────────────────────────

_engine_instance: Optional[OrderFlowEngine] = None


def get_engine() -> OrderFlowEngine:
    """Return the module-level singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = OrderFlowEngine()
    return _engine_instance


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ─── CLI test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s — %(message)s")
    coins = sys.argv[1:] or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    eng = OrderFlowEngine()
    print("\n" + "=" * 75)
    print("ORDER FLOW ENGINE v2 — Multi-Exchange + Order Blocks")
    print("=" * 75)
    for sym in coins:
        sig = eng.get_signal(sym)
        if sig is None:
            print(f"{sym:<12} — no data")
            continue
        bar = "▓" * int(abs(sig.score) * 20)
        direction = "▲" if sig.score > 0 else ("▼" if sig.score < 0 else "─")
        print(
            f"\n{sym:<12} score={sig.score:+.3f} {direction}{bar}"
            f"  exchanges={sig.exchange_count}"
        )
        print(
            f"  book={sig.book_imbalance:+.3f}"
            f"  taker={sig.taker_buy_ratio:.2f}"
            f"  delta={sig.cumulative_delta:+.3f}"
            f"  L/S={sig.ls_ratio:.2f}"
        )
        print(
            f"  agg_bid=${sig.aggregated_bid_usd:,.0f}"
            f"  agg_ask=${sig.aggregated_ask_usd:,.0f}"
        )
        if sig.bid_walls:
            for w in sig.bid_walls[:3]:
                print(f"  BID WALL  ${w.price:>12,.2f}  ${w.size_usd:>10,.0f}  ({w.multiple:.1f}× avg) [{w.exchange}]")
        if sig.ask_walls:
            for w in sig.ask_walls[:3]:
                print(f"  ASK WALL  ${w.price:>12,.2f}  ${w.size_usd:>10,.0f}  ({w.multiple:.1f}× avg) [{w.exchange}]")
        if sig.order_blocks:
            print(f"  ORDER BLOCKS ({len(sig.order_blocks)}):")
            for ob in sig.order_blocks:
                tested_str = "TESTED" if ob.tested else "FRESH"
                print(
                    f"    {ob.type.upper():<8} ${ob.zone_low:>10,.2f} — ${ob.zone_high:>10,.2f}"
                    f"  str={ob.strength:.2f}  age={ob.age_hours:.0f}h  {tested_str}"
                )
        if sig.nearest_bullish_ob:
            print(f"  Nearest bullish OB: ${sig.nearest_bullish_ob:,.2f}")
        if sig.nearest_bearish_ob:
            print(f"  Nearest bearish OB: ${sig.nearest_bearish_ob:,.2f}")
        if sig.note:
            print(f"  Note: {sig.note}")
    print("\n" + "=" * 75)
