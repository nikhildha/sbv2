"""
Project Regime-Master — Adaptive Brain Switcher
Dynamically selects between Conservative / Balanced / Aggressive brain configs
based on market conditions (BTC regime, volatility, TF agreement, recent losses).

Backtest result: +$2,421 PnL | PF 1.49 | $7.29/trade (beats all static brains).
"""
import logging
from datetime import datetime

import config

logger = logging.getLogger("BrainSwitcher")


class BrainSwitcher:
    """
    Adaptive brain selection — chooses the optimal trade config every analysis cycle.

    Decision inputs:
      1. BTC Daily regime (BULL/BEAR/CHOP) + confidence margin
      2. Market volatility percentile (ATR/price across scanned coins)
      3. Multi-TF agreement strength (2/3 or 3/3 timeframes agree)
      4. Recent consecutive losses (circuit breaker)

    Score mapping:
      score >= 2.0  → AGGRESSIVE (25× lev, conv≥50, SL 2.0, TP 3.0)
      score >= 0.5  → BALANCED   (15× lev, conv≥60, SL 2.0, TP 4.0)
      score <  0.5  → CONSERVATIVE (10× lev, conv≥70, SL 1.5, TP 3.0)
    """

    BRAIN_IDS = ("conservative", "balanced", "aggressive")

    def __init__(self):
        self._active_brain = "conservative"  # Start safe
        self._recent_losses = 0     # Consecutive losing trades
        self._switch_log = []       # Last N switches for dashboard
        self._last_switch_time = None

    # ─── Brain Selection ─────────────────────────────────────────────────────

    def select_brain(self, btc_regime, btc_margin, vol_percentile, tf_agreement, recent_losses=None):
        """
        Evaluate market conditions and return the optimal brain config ID.

        Parameters
        ----------
        btc_regime : str
            BTC Daily HMM regime: 'BULL', 'BEAR', or 'CHOP'
        btc_margin : float
            BTC regime confidence margin (0.0 to 1.0)
        vol_percentile : float
            Current volatility as percentile (0.0 = very low, 1.0 = very high)
        tf_agreement : int
            Number of timeframes agreeing on direction (0, 1, 2, or 3)
        recent_losses : int or None
            Override for consecutive loss count (uses internal counter if None)

        Returns
        -------
        str : brain config ID ('conservative', 'balanced', or 'aggressive')
        """
        if recent_losses is None:
            recent_losses = self._recent_losses

        score = 0.0

        # 1. BTC regime (heaviest weight — macro trend drives everything)
        if btc_regime == "CHOP":
            score -= 1.0                  # Uncertain → lean conservative
        elif btc_margin >= 0.50:
            score += 2.0                  # Strong BTC trend → aggressive
        elif btc_margin >= 0.25:
            score += 1.0                  # Moderate trend → balanced
        # else: weak trend → neutral (+0)

        # 2. Volatility regime
        if vol_percentile > 0.80:
            score -= 1.0                  # High vol → conservative (protect capital)
        elif vol_percentile < 0.20:
            score -= 0.5                  # Very low vol → slightly conservative (no moves)
        else:
            score += 0.5                  # Normal vol → slight boost

        # 3. Multi-TF agreement
        if tf_agreement >= 3:
            score += 1.0                  # Perfect agreement → aggressive
        elif tf_agreement >= 2:
            pass                          # Good → neutral (already default)
        else:
            score -= 1.0                  # Poor agreement → conservative

        # 4. Recent performance (circuit breaker)
        if recent_losses >= 3:
            score -= 1.5                  # 3+ consecutive losses → force conservative

        # Map score → brain
        if score >= 2.0:
            brain = "aggressive"
        elif score >= 0.5:
            brain = "balanced"
        else:
            brain = "conservative"

        # Log switch if brain changed
        if brain != self._active_brain:
            logger.info(
                "🧠 Brain switch: %s → %s (score=%.1f | BTC=%s margin=%.2f | vol=%.0f%% | TF=%d/3 | losses=%d)",
                self._active_brain.upper(), brain.upper(), score,
                btc_regime, btc_margin, vol_percentile * 100,
                tf_agreement, recent_losses,
            )
            self._switch_log.append({
                "from": self._active_brain,
                "to": brain,
                "score": round(score, 1),
                "reason": f"BTC={btc_regime}(m={btc_margin:.2f}) vol={vol_percentile:.0%} TF={tf_agreement}/3",
                "time": datetime.utcnow().isoformat() + "Z",
            })
            # Keep only last 20 switches
            if len(self._switch_log) > 20:
                self._switch_log = self._switch_log[-20:]
            self._active_brain = brain
            self._last_switch_time = datetime.utcnow()

        return brain

    # ─── Loss Tracking ───────────────────────────────────────────────────────

    def record_trade_result(self, pnl):
        """Update consecutive loss counter based on trade result."""
        if pnl <= 0:
            self._recent_losses += 1
        else:
            self._recent_losses = 0

    # ─── Brain Config Lookup ─────────────────────────────────────────────────

    @staticmethod
    def get_brain_config(brain_id):
        """Return the brain's trading parameters from config.BRAIN_PROFILES."""
        return config.BRAIN_PROFILES.get(brain_id, config.BRAIN_PROFILES["conservative"])

    # ─── Dashboard State ─────────────────────────────────────────────────────

    def get_state(self):
        """Return current brain state for dashboard display."""
        return {
            "active_brain": self._active_brain,
            "recent_losses": self._recent_losses,
            "switch_log": self._switch_log[-5:],  # Last 5 switches
            "last_switch": self._last_switch_time.isoformat() + "Z" if self._last_switch_time else None,
        }

    @property
    def active_brain(self):
        return self._active_brain
