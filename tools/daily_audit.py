#!/usr/bin/env python3
"""
tools/daily_audit.py — HMMBOT Master Daily Audit (Python Engine Side)

Checks performed:
  P4  — Exchange Position Sync  (LIVE mode only)
  P5  — bot_id Stamping
  P7  — Engine API Health
  P8  — Data Pipeline (last analysis freshness)
  P11 — Process Health (heartbeat / cycle count)
  P12 — Log Quality (ERROR/CRITICAL scan)
  I2  — bot_id / bot_name env vars set
  I4  — Trade count: tradebook vs deployed_count
  I7  — Leverage Bounds ({10, 15, 25, 35})
  I8  — Coin Tier Compliance (no Tier C in active trades)
  I9  — SL/TP Geometry validity
  I10 — HMM Signal Quality (confidence distribution)

Output:
  stdout: human-readable report
  data/audit_report_engine.json: machine-readable (merged by audit_runner.sh)

Exit codes: 0 = all pass, 1 = warnings, 2 = any FAIL

Usage:
  python tools/daily_audit.py
  python tools/daily_audit.py --json          # JSON-only stdout
  python tools/daily_audit.py --checks P7,P11 # Run specific checks only
"""
import sys
import os
import json
import time
import csv
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Path setup — ensure project root is importable ──────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402

# ─── Constants ────────────────────────────────────────────────────────
ENGINE_PORT    = int(os.environ.get("PORT", 3001))
ENGINE_BASE    = f"http://localhost:{ENGINE_PORT}"
ENGINE_SECRET  = os.environ.get("ENGINE_API_SECRET", "")
VALID_LEVERAGES = {10, 15, 25, 35}
MAX_HEARTBEAT_AGE_S = 120      # P11: engine must have cycled within 2 min
MAX_ANALYSIS_AGE_S  = 600      # P8:  last full analysis must be < 10 min old
LOG_FILE        = os.path.join(config.DATA_DIR, "bot.log")
AUDIT_OUT       = os.path.join(config.DATA_DIR, "audit_report_engine.json")
REPORT_LINES    = 500          # P12: scan last N log lines

# ─── Helpers ──────────────────────────────────────────────────────────

def _now_ts() -> float:
    return time.time()

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

def _result(check_id: str, status: str, message: str, detail: dict = None) -> dict:
    """Standard result envelope."""
    return {
        "check":   check_id,
        "status":  status,   # PASS | WARN | FAIL | SKIP
        "message": message,
        "detail":  detail or {},
        "ts":      _utcnow(),
    }

def _read_json_safe(path: str, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}

def _call_engine(path: str, timeout: int = 5):
    """Call engine REST API. Returns (ok, data, latency_ms)."""
    import urllib.request
    url = f"{ENGINE_BASE}{path}"
    headers = {}
    if ENGINE_SECRET:
        headers["Authorization"] = f"Bearer {ENGINE_SECRET}"
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            lat = int((time.monotonic() - t0) * 1000)
            return True, json.loads(resp.read()), lat
    except Exception as e:
        lat = int((time.monotonic() - t0) * 1000)
        return False, {"error": str(e)}, lat

def _parse_iso(ts_str: str):
    """Parse ISO 8601 string → aware datetime. Returns None on failure."""
    if not ts_str:
        return None
    try:
        # Handle 'Z' suffix
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None

def _age_seconds(ts_str: str) -> float:
    """Seconds since an ISO timestamp. Returns float('inf') if unparseable."""
    dt = _parse_iso(ts_str)
    if not dt:
        return float("inf")
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds()

# ─── Check Implementations ────────────────────────────────────────────

def check_p4_exchange_sync() -> dict:
    """P4: Exchange Position Sync (LIVE mode only)."""
    if config.PAPER_TRADE:
        return _result("P4", "SKIP", "PAPER mode — exchange sync not applicable")

    tradebook = _read_json_safe(os.path.join(config.DATA_DIR, "tradebook.json"))
    live_trades = [t for t in tradebook.get("trades", [])
                   if t.get("status") == "ACTIVE" and (t.get("mode") or "").upper().startswith("LIVE")]

    try:
        import coindcx_client as cdx
        positions = cdx.list_positions()
        exchange_symbols = {
            cdx.from_coindcx_pair(p.get("pair", ""))
            for p in positions
            if float(p.get("active_pos", 0)) != 0
        }
        exchange_symbols.discard("")
    except Exception as e:
        return _result("P4", "FAIL", f"CoinDCX API error: {e}")

    tb_symbols = {t.get("symbol", "") for t in live_trades}
    ghost_exchange = tb_symbols - exchange_symbols   # in TB, not on exchange
    orphan_exchange = exchange_symbols - tb_symbols  # on exchange, not in TB

    if ghost_exchange or orphan_exchange:
        return _result("P4", "FAIL",
                       f"Sync mismatch: {len(ghost_exchange)} ghost(s), {len(orphan_exchange)} orphan(s)",
                       {"ghost_in_tradebook": list(ghost_exchange),
                        "orphan_on_exchange": list(orphan_exchange)})

    return _result("P4", "PASS",
                   f"Exchange sync OK — {len(tb_symbols)} live trade(s) matched",
                   {"live_symbols": sorted(tb_symbols)})


def check_p5_bot_id() -> dict:
    """P5: bot_id stamping on all tradebook trades."""
    expected_bot_id   = config.ENGINE_BOT_ID
    expected_bot_name = config.ENGINE_BOT_NAME
    tradebook = _read_json_safe(os.path.join(config.DATA_DIR, "tradebook.json"))
    trades = tradebook.get("trades", [])

    if not trades:
        return _result("P5", "PASS", "Tradebook empty — nothing to stamp-check")

    missing_id   = [t.get("trade_id", "?") for t in trades if not t.get("bot_id")]
    wrong_id     = [t.get("trade_id", "?") for t in trades
                    if t.get("bot_id") and expected_bot_id and t.get("bot_id") != expected_bot_id]
    missing_name = [t.get("trade_id", "?") for t in trades if not t.get("bot_name")]

    issues = []
    if missing_id:
        issues.append(f"{len(missing_id)} trade(s) missing bot_id")
    if wrong_id:
        issues.append(f"{len(wrong_id)} trade(s) with wrong bot_id")
    if missing_name:
        issues.append(f"{len(missing_name)} trade(s) missing bot_name")

    if issues:
        status = "FAIL" if missing_id or wrong_id else "WARN"
        return _result("P5", status, "; ".join(issues),
                       {"missing_id": missing_id[:5], "wrong_id": wrong_id[:5], "missing_name": missing_name[:5]})

    return _result("P5", "PASS",
                   f"All {len(trades)} trades stamped correctly",
                   {"engine_bot_id": expected_bot_id, "engine_bot_name": expected_bot_name})


def check_p7_api_health() -> dict:
    """P7: Engine API health — ping all endpoints."""
    checks = [
        ("/api/health", ["status"]),
        ("/api/all",    ["multi", "tradebook", "engine"]),
        ("/api/logs",   ["lines"]),
    ]
    results = []
    all_ok = True
    for path, required_keys in checks:
        ok, data, lat = _call_engine(path)
        missing = [k for k in required_keys if k not in data] if ok else required_keys
        endpoint_ok = ok and not missing
        results.append({
            "endpoint": path,
            "ok": endpoint_ok,
            "latency_ms": lat,
            "missing_keys": missing,
            "error": data.get("error") if not ok else None,
        })
        if not endpoint_ok:
            all_ok = False

    avg_lat = int(sum(r["latency_ms"] for r in results) / len(results))
    if all_ok:
        status = "WARN" if avg_lat > 2000 else "PASS"
        msg = f"{len(checks)}/{len(checks)} endpoints OK — avg {avg_lat}ms"
        if avg_lat > 2000:
            msg += " (SLOW)"
    else:
        status = "FAIL"
        failed = [r["endpoint"] for r in results if not r["ok"]]
        msg = f"Endpoint(s) failing: {', '.join(failed)}"

    return _result("P7", status, msg, {"endpoints": results})


def check_p8_data_pipeline() -> dict:
    """P8: Data pipeline freshness — last analysis time."""
    multi = _read_json_safe(os.path.join(config.DATA_DIR, "multi_bot_state.json"))
    last_analysis = multi.get("last_analysis_time")
    age = _age_seconds(last_analysis)
    coins = len(multi.get("coin_states", {}))

    if age == float("inf"):
        return _result("P8", "WARN", "multi_bot_state.json missing last_analysis_time (engine may not have run yet)")

    if age > MAX_ANALYSIS_AGE_S:
        return _result("P8", "FAIL",
                       f"Last analysis {int(age)}s ago — exceeds {MAX_ANALYSIS_AGE_S}s threshold",
                       {"last_analysis_time": last_analysis, "age_seconds": int(age), "coins_scanned": coins})

    return _result("P8", "PASS",
                   f"Last analysis {int(age)}s ago — {coins} coins scanned",
                   {"last_analysis_time": last_analysis, "age_seconds": int(age), "coins_scanned": coins})


def check_p11_process_health() -> dict:
    """P11: Process health — heartbeat age and cycle count."""
    engine_state = _read_json_safe(os.path.join(config.DATA_DIR, "engine_state.json"))
    multi        = _read_json_safe(os.path.join(config.DATA_DIR, "multi_bot_state.json"))

    cycle_count   = engine_state.get("cycle_count", 0)
    last_analysis = multi.get("last_analysis_time") or engine_state.get("last_cycle_time")
    age           = _age_seconds(last_analysis)

    if age == float("inf"):
        return _result("P11", "WARN",
                       "No heartbeat timestamp found — engine may not have started",
                       {"cycle_count": cycle_count})

    if age > MAX_HEARTBEAT_AGE_S:
        return _result("P11", "FAIL",
                       f"Heartbeat {int(age)}s ago — engine may be stuck (threshold={MAX_HEARTBEAT_AGE_S}s)",
                       {"last_heartbeat": last_analysis, "age_seconds": int(age), "cycle_count": cycle_count})

    return _result("P11", "PASS",
                   f"Engine alive — heartbeat {int(age)}s ago — cycle #{cycle_count}",
                   {"last_heartbeat": last_analysis, "age_seconds": int(age), "cycle_count": cycle_count})


def check_p12_log_quality() -> dict:
    """P12: Log quality — ERROR/CRITICAL scan of last N lines."""
    if not os.path.exists(LOG_FILE):
        return _result("P12", "WARN", f"Log file not found: {LOG_FILE}")

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        last_lines = lines[-REPORT_LINES:]
    except Exception as e:
        return _result("P12", "FAIL", f"Cannot read log file: {e}")

    errors   = [l.strip() for l in last_lines if " ERROR" in l or " CRITICAL" in l]
    criticals = [l.strip() for l in last_lines if " CRITICAL" in l]

    if criticals:
        return _result("P12", "FAIL",
                       f"{len(criticals)} CRITICAL and {len(errors)} ERROR lines in last {REPORT_LINES} log lines",
                       {"error_count": len(errors), "critical_count": len(criticals),
                        "worst_lines": criticals[:3]})

    if len(errors) > 10:
        return _result("P12", "WARN",
                       f"{len(errors)} ERROR lines in last {REPORT_LINES} log lines",
                       {"error_count": len(errors), "sample": errors[:3]})

    return _result("P12", "PASS",
                   f"Log quality OK — {len(errors)} ERROR(s) in last {REPORT_LINES} lines",
                   {"error_count": len(errors), "total_lines_scanned": len(last_lines)})


def check_i2_bot_id_env() -> dict:
    """I2: ENGINE_BOT_ID and ENGINE_BOT_NAME env vars set."""
    bot_id   = config.ENGINE_BOT_ID
    bot_name = config.ENGINE_BOT_NAME

    missing = []
    if not bot_id:
        missing.append("ENGINE_BOT_ID")
    if not bot_name:
        missing.append("ENGINE_BOT_NAME")

    if missing:
        return _result("I2", "FAIL",
                       f"Missing Railway env vars: {', '.join(missing)} — trade isolation broken",
                       {"missing": missing})

    return _result("I2", "PASS",
                   f"bot_id={bot_id[:12]}… bot_name={bot_name}",
                   {"bot_id": bot_id, "bot_name": bot_name})


def check_i4_trade_count() -> dict:
    """I4: Trade count match — tradebook vs deployed_count."""
    tradebook = _read_json_safe(os.path.join(config.DATA_DIR, "tradebook.json"))
    multi     = _read_json_safe(os.path.join(config.DATA_DIR, "multi_bot_state.json"))

    tb_active    = [t for t in tradebook.get("trades", []) if t.get("status") == "ACTIVE"]
    tb_count     = len(tb_active)
    deployed     = multi.get("deployed_count", 0)

    drift = abs(tb_count - deployed)
    if drift > 2:
        return _result("I4", "WARN",
                       f"Trade count drift: tradebook={tb_count} vs deployed_count={deployed} (diff={drift})",
                       {"tradebook_active": tb_count, "multi_deployed": deployed, "drift": drift})

    return _result("I4", "PASS",
                   f"Trade counts aligned — tradebook={tb_count}, deployed_count={deployed}",
                   {"tradebook_active": tb_count, "multi_deployed": deployed})


def check_i7_leverage_bounds() -> dict:
    """I7: All active trades use valid leverage tiers."""
    tradebook = _read_json_safe(os.path.join(config.DATA_DIR, "tradebook.json"))
    active = [t for t in tradebook.get("trades", []) if t.get("status") == "ACTIVE"]

    violations = []
    for t in active:
        lev = t.get("leverage", 0)
        if lev not in VALID_LEVERAGES and lev != 0:
            violations.append({"trade_id": t.get("trade_id"), "symbol": t.get("symbol"), "leverage": lev})

    if violations:
        return _result("I7", "WARN",
                       f"{len(violations)} trade(s) with unexpected leverage value",
                       {"violations": violations[:5], "valid_leverages": sorted(VALID_LEVERAGES)})

    return _result("I7", "PASS",
                   f"All {len(active)} active trade(s) within valid leverage tiers",
                   {"valid_leverages": sorted(VALID_LEVERAGES), "active_count": len(active)})


def check_i8_coin_tier_compliance() -> dict:
    """I8: No Tier C coins in active trades."""
    tier_file = config.COIN_TIER_FILE
    if not os.path.exists(tier_file):
        return _result("I8", "WARN", f"Coin tier file not found: {tier_file}")

    tier_c = set()
    try:
        with open(tier_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                coin = (row.get("coin") or row.get("symbol") or "").strip().upper()
                tier = (row.get("tier") or "").strip().upper()
                if tier == "C" and coin:
                    # Convert "BTC" → "BTCUSDT" if needed
                    sym = coin if coin.endswith("USDT") else coin + "USDT"
                    tier_c.add(sym)
    except Exception as e:
        return _result("I8", "FAIL", f"Cannot read coin tier file: {e}")

    tradebook = _read_json_safe(os.path.join(config.DATA_DIR, "tradebook.json"))
    active = [t for t in tradebook.get("trades", []) if t.get("status") == "ACTIVE"]

    violations = [
        {"trade_id": t.get("trade_id"), "symbol": t.get("symbol")}
        for t in active
        if (t.get("symbol") or "") in tier_c
    ]

    if violations:
        return _result("I8", "FAIL",
                       f"{len(violations)} active trade(s) in Tier C (should not be traded)",
                       {"violations": violations, "tier_c_count": len(tier_c)})

    return _result("I8", "PASS",
                   f"No Tier C coins in {len(active)} active trade(s)",
                   {"active_count": len(active), "tier_c_total": len(tier_c)})


def check_i9_sltp_validity() -> dict:
    """I9: SL/TP geometry — BUY: sl < entry < tp; SELL: tp < entry < sl."""
    tradebook = _read_json_safe(os.path.join(config.DATA_DIR, "tradebook.json"))
    active = [t for t in tradebook.get("trades", []) if t.get("status") == "ACTIVE"]

    violations = []
    for t in active:
        entry = t.get("entry_price", 0)
        sl    = t.get("sl", 0)
        tp    = t.get("tp", 0)
        side  = (t.get("side") or "").upper()

        if not (entry and sl and tp):
            continue  # Skip if any value is zero/missing

        valid = True
        if side == "BUY":
            valid = sl < entry < tp
        elif side == "SELL":
            valid = tp < entry < sl

        if not valid:
            violations.append({
                "trade_id": t.get("trade_id"),
                "symbol":   t.get("symbol"),
                "side":     side,
                "entry":    entry,
                "sl":       sl,
                "tp":       tp,
            })

    if violations:
        return _result("I9", "WARN",
                       f"{len(violations)} trade(s) with invalid SL/TP geometry",
                       {"violations": violations[:5]})

    return _result("I9", "PASS",
                   f"SL/TP geometry valid on all {len(active)} active trade(s)")


def check_i10_hmm_signal_quality() -> dict:
    """I10: HMM confidence distribution from multi_bot_state."""
    multi = _read_json_safe(os.path.join(config.DATA_DIR, "multi_bot_state.json"))
    coin_states = multi.get("coin_states", {})

    if not coin_states:
        return _result("I10", "WARN", "No coin states found — engine may not have run a full scan yet")

    confidences = [
        v.get("confidence", 0)
        for v in coin_states.values()
        if isinstance(v, dict) and "confidence" in v
    ]

    if not confidences:
        return _result("I10", "WARN", "No confidence values in coin_states")

    avg_conf = sum(confidences) / len(confidences)
    min_conf = min(confidences)
    max_conf = max(confidences)

    # Degenerate: all states identical (model stuck in one regime)
    regimes = {v.get("regime") for v in coin_states.values() if isinstance(v, dict)}
    degenerate = len(regimes) <= 1 and len(coin_states) > 5

    if degenerate:
        return _result("I10", "WARN",
                       f"Degenerate HMM — all {len(coin_states)} coins predict same regime: {regimes}",
                       {"avg_confidence": round(avg_conf, 3), "regimes_seen": list(regimes)})

    if avg_conf < 0.15:
        return _result("I10", "WARN",
                       f"Very low avg confidence: {avg_conf:.3f} — model may need retraining",
                       {"avg": round(avg_conf, 3), "min": round(min_conf, 3), "max": round(max_conf, 3)})

    return _result("I10", "PASS",
                   f"HMM signal quality OK — avg conf {avg_conf:.3f} across {len(coin_states)} coins",
                   {"avg": round(avg_conf, 3), "min": round(min_conf, 3),
                    "max": round(max_conf, 3), "coins_with_confidence": len(confidences)})


# ─── P13: Engine Crash History ────────────────────────────────────────

def check_p13_crash_history() -> dict:
    """P13: Engine crash history — check for recent crash files."""
    crash_file = os.path.join(config.DATA_DIR, "engine_crash.json")
    if not os.path.exists(crash_file):
        return _result("P13", "PASS", "No crash file found — engine has not crashed")

    crash_data = _read_json_safe(crash_file)
    crashes = crash_data if isinstance(crash_data, list) else [crash_data]

    # Check for recent crashes (last 1 hour)
    recent_crashes = []
    for c in crashes:
        ts = c.get("timestamp") or c.get("ts", "")
        age = _age_seconds(ts)
        if age < 3600:  # Last 1 hour
            recent_crashes.append(c)

    crash_type = crashes[-1].get("crash_type", "unknown") if crashes else "unknown"
    last_crash_ts = crashes[-1].get("timestamp", "unknown") if crashes else "unknown"

    if len(recent_crashes) >= 3:
        return _result("P13", "FAIL",
                       f"{len(recent_crashes)} crashes in the last hour — engine in crash loop",
                       {"recent_crashes": len(recent_crashes), "last_crash_type": crash_type,
                        "last_crash_ts": last_crash_ts, "total_crashes": len(crashes)})

    if recent_crashes:
        return _result("P13", "WARN",
                       f"{len(recent_crashes)} crash(es) in the last hour (type: {crash_type})",
                       {"recent_crashes": len(recent_crashes), "last_crash_type": crash_type,
                        "last_crash_ts": last_crash_ts})

    return _result("P13", "PASS",
                   f"No recent crashes — last crash: {last_crash_ts} (type: {crash_type})",
                   {"total_crashes": len(crashes), "last_crash_type": crash_type})


# ─── P14: Watchdog & Thread Health ────────────────────────────────────

def check_p14_watchdog_thread() -> dict:
    """P14: Verify engine thread and watchdog are alive via /api/health."""
    ok, data, lat = _call_engine("/api/health")
    if not ok:
        return _result("P14", "FAIL",
                       f"Engine API unreachable — watchdog cannot be verified",
                       {"error": data.get("error"), "latency_ms": lat})

    engine_status = data.get("status", "unknown")
    crash_count = data.get("crash_count", -1)
    uptime_min = data.get("uptime_minutes", 0)

    if engine_status in ("stopped", "crashed"):
        return _result("P14", "FAIL",
                       f"Engine status='{engine_status}' — thread is not running",
                       {"status": engine_status, "crash_count": crash_count,
                        "uptime_minutes": uptime_min})

    if crash_count > 0:
        severity = "FAIL" if crash_count >= 3 else "WARN"
        return _result("P14", severity,
                       f"Engine running but {crash_count} crash(es) recorded this session (uptime: {uptime_min:.0f}min)",
                       {"status": engine_status, "crash_count": crash_count,
                        "uptime_minutes": uptime_min})

    return _result("P14", "PASS",
                   f"Engine healthy — status='{engine_status}', uptime={uptime_min:.0f}min, 0 crashes",
                   {"status": engine_status, "crash_count": 0, "uptime_minutes": uptime_min})


# ─── P15: Brain Cache Pressure ────────────────────────────────────────

def check_p15_brain_cache_pressure() -> dict:
    """P15: Check HMM brain cache size — OOM risk indicator."""
    ok, data, lat = _call_engine("/api/all")
    if not ok:
        return _result("P15", "SKIP", "Engine unreachable — brain cache check skipped")

    engine_data = data.get("engine", {})
    # Check multi_bot_state for coin count (proxy for brain cache size)
    multi = data.get("multi", {})
    coin_states = multi.get("coin_states", {})
    brain_count = len(coin_states)
    BRAIN_CACHE_MAX = 60  # matches main.py _BRAIN_CACHE_MAX

    if brain_count >= BRAIN_CACHE_MAX:
        return _result("P15", "WARN",
                       f"Brain cache at capacity: {brain_count}/{BRAIN_CACHE_MAX} — LRU eviction active",
                       {"brain_count": brain_count, "max": BRAIN_CACHE_MAX,
                        "risk": "Memory pressure, may trigger OOM on Railway"})

    if brain_count >= BRAIN_CACHE_MAX * 0.8:
        return _result("P15", "WARN",
                       f"Brain cache nearing capacity: {brain_count}/{BRAIN_CACHE_MAX} ({brain_count/BRAIN_CACHE_MAX*100:.0f}%)",
                       {"brain_count": brain_count, "max": BRAIN_CACHE_MAX})

    return _result("P15", "PASS",
                   f"Brain cache healthy: {brain_count}/{BRAIN_CACHE_MAX} entries",
                   {"brain_count": brain_count, "max": BRAIN_CACHE_MAX})


# ─── P16: Engine Restart Loop Detection ───────────────────────────────

def check_p16_restart_loop() -> dict:
    """P16: Detect if engine is stuck in a restart loop (short uptimes)."""
    ok, data, lat = _call_engine("/api/health")
    if not ok:
        return _result("P16", "FAIL", "Engine API unreachable",
                       {"error": data.get("error")})

    crash_count = data.get("crash_count", 0)
    uptime_min = data.get("uptime_minutes", 0)
    last_crash = data.get("last_crash", "")

    # If uptime < 5 min AND crash_count > 2, likely in restart loop
    if uptime_min < 5 and crash_count >= 2:
        return _result("P16", "FAIL",
                       f"Restart loop detected: uptime={uptime_min:.1f}min, {crash_count} crashes",
                       {"uptime_minutes": uptime_min, "crash_count": crash_count,
                        "last_crash": last_crash,
                        "action": "Check logs for repeating init errors"})

    if crash_count >= 3:
        return _result("P16", "WARN",
                       f"High crash count ({crash_count}) but stable uptime ({uptime_min:.0f}min) — recovered",
                       {"uptime_minutes": uptime_min, "crash_count": crash_count})

    return _result("P16", "PASS",
                   f"No restart loop — uptime={uptime_min:.0f}min, crashes={crash_count}",
                   {"uptime_minutes": uptime_min, "crash_count": crash_count})


# ─── Check Registry ───────────────────────────────────────────────────

def check_p9_coin_tiers() -> dict:
    """P9: Coin tier file exists and has valid Tier A entries."""
    tier_file = config.COIN_TIER_FILE
    if not os.path.exists(tier_file):
        return _result("P9", "FAIL", f"Coin tier file missing: {tier_file}")

    try:
        tier_a, tier_b, tier_c = [], [], []
        with open(tier_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                coin = (row.get("coin") or row.get("symbol") or "").strip()
                tier = (row.get("tier") or "").strip().upper()
                if tier == "A":
                    tier_a.append(coin)
                elif tier == "B":
                    tier_b.append(coin)
                elif tier == "C":
                    tier_c.append(coin)
    except Exception as e:
        return _result("P9", "FAIL", f"Cannot parse coin tier file: {e}")

    if len(tier_a) < 5:
        return _result("P9", "FAIL",
                       f"Too few Tier A coins: {len(tier_a)} (need ≥ 5 to trade)",
                       {"tier_a": tier_a, "tier_b_count": len(tier_b), "tier_c_count": len(tier_c)})

    return _result("P9", "PASS",
                   f"Coin tiers OK — A:{len(tier_a)}, B:{len(tier_b)}, C:{len(tier_c)}",
                   {"tier_a_count": len(tier_a), "tier_b_count": len(tier_b), "tier_c_count": len(tier_c)})


ALL_CHECKS = {
    "P4":  check_p4_exchange_sync,
    "P5":  check_p5_bot_id,
    "P7":  check_p7_api_health,
    "P8":  check_p8_data_pipeline,
    "P9":  check_p9_coin_tiers,
    "P11": check_p11_process_health,
    "P12": check_p12_log_quality,
    "P13": check_p13_crash_history,
    "P14": check_p14_watchdog_thread,
    "P15": check_p15_brain_cache_pressure,
    "P16": check_p16_restart_loop,
    "I2":  check_i2_bot_id_env,
    "I4":  check_i4_trade_count,
    "I7":  check_i7_leverage_bounds,
    "I8":  check_i8_coin_tier_compliance,
    "I9":  check_i9_sltp_validity,
    "I10": check_i10_hmm_signal_quality,
}

STATUS_ICON = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌", "SKIP": "⏭️ "}


def run_checks(check_ids: list = None) -> list:
    """Run selected checks (or all). Returns list of result dicts."""
    targets = check_ids or list(ALL_CHECKS.keys())
    results = []
    for cid in targets:
        fn = ALL_CHECKS.get(cid)
        if not fn:
            print(f"  Unknown check: {cid}", file=sys.stderr)
            continue
        try:
            r = fn()
        except Exception as e:
            r = _result(cid, "FAIL", f"Check raised exception: {e}")
        results.append(r)
    return results


def print_report(results: list, run_ts: str):
    """Print human-readable audit report."""
    passed  = sum(1 for r in results if r["status"] == "PASS")
    warned  = sum(1 for r in results if r["status"] == "WARN")
    failed  = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")

    print()
    print("═" * 65)
    print(f"  HMMBOT ENGINE AUDIT — {run_ts}")
    print("═" * 65)
    print()
    for r in results:
        icon = STATUS_ICON.get(r["status"], "?")
        print(f"  {icon} {r['check']:<4}  {r['message']}")
    print()
    print("─" * 65)
    print(f"  SUMMARY: ✅ {passed} PASS  ⚠️  {warned} WARN  "
          f"❌ {failed} FAIL  ⏭️  {skipped} SKIP")
    if failed > 0:
        fails = [r for r in results if r["status"] == "FAIL"]
        print(f"\n  CRITICAL FAILURES:")
        for r in fails:
            print(f"    {r['check']}: {r['message']}")
    print("═" * 65)
    print()


def main():
    parser = argparse.ArgumentParser(description="HMMBOT Daily Audit — Engine Side")
    parser.add_argument("--json",   action="store_true", help="JSON-only stdout")
    parser.add_argument("--checks", type=str, default="",
                        help="Comma-separated check IDs (e.g. P7,P11). Default: all")
    args = parser.parse_args()

    check_ids = [c.strip().upper() for c in args.checks.split(",") if c.strip()] or None
    run_ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    results = run_checks(check_ids)

    # Write machine-readable output
    report = {
        "section":  "engine",
        "run_ts":   _utcnow(),
        "results":  results,
        "summary": {
            "pass":    sum(1 for r in results if r["status"] == "PASS"),
            "warn":    sum(1 for r in results if r["status"] == "WARN"),
            "fail":    sum(1 for r in results if r["status"] == "FAIL"),
            "skip":    sum(1 for r in results if r["status"] == "SKIP"),
            "total":   len(results),
        },
    }
    try:
        with open(AUDIT_OUT, "w") as f:
            json.dump(report, f, indent=2)
    except Exception as e:
        print(f"[audit] Warning: could not write {AUDIT_OUT}: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(results, run_ts)

    # Exit code
    if any(r["status"] == "FAIL" for r in results):
        sys.exit(2)
    elif any(r["status"] == "WARN" for r in results):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
