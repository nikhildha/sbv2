import sys
import os

# Ensure we can import from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from coin_scanner import get_active_bot_segment_pool, get_hottest_segments
from data_pipeline import fetch_klines, get_current_price
from feature_engine import compute_hmm_features

def main():
    print("========== DATA FEED & SEGMENT ROUTER VERIFICATION ==========\n")
    
    print("1. Testing get_hottest_segments (Absolute Momentum Ranking)")
    print("-" * 60)
    try:
        hot = get_hottest_segments()
        print("Top Segments returned:")
        for i, seg in enumerate(hot):
            print(f"  {i+1}. {seg}")
    except Exception as e:
        print(f"❌ Error in get_hottest_segments: {e}")

    print("\n2. Testing get_active_bot_segment_pool with a 'Main Bot' (Segment: ALL)")
    print("-" * 60)
    config.ENGINE_ACTIVE_BOTS = [{"bot_id": "test_main", "segment_filter": "ALL"}]
    try:
        pool_all = get_active_bot_segment_pool(config.ENGINE_ACTIVE_BOTS)
        print(f"Active pool has {len(pool_all)} coins: {pool_all}")
    except Exception as e:
        print(f"❌ Error in get_active_bot_segment_pool (ALL): {e}")

    print("\n3. Testing get_active_bot_segment_pool with a 'DeFi Bot' (Segment: DeFi)")
    print("-" * 60)
    config.ENGINE_ACTIVE_BOTS = [{"bot_id": "test_defi", "segment_filter": "DeFi"}]
    try:
        pool_defi = get_active_bot_segment_pool(config.ENGINE_ACTIVE_BOTS)
        print(f"Active pool has {len(pool_defi)} coins: {pool_defi}")
    except Exception as e:
        print(f"❌ Error in get_active_bot_segment_pool (DeFi): {e}")

    print("\n4. Testing get_active_bot_segment_pool with mixed bots (ALL + AI)")
    print("-" * 60)
    config.ENGINE_ACTIVE_BOTS = [
        {"bot_id": "test_main", "segment_filter": "ALL"},
        {"bot_id": "test_ai", "segment_filter": "AI"}
    ]
    try:
        pool_mixed = get_active_bot_segment_pool(config.ENGINE_ACTIVE_BOTS)
        print(f"Active pool has {len(pool_mixed)} coins: {pool_mixed}")
    except Exception as e:
        print(f"❌ Error in get_active_bot_segment_pool (Mixed): {e}")

    print("\n5. Testing Data Pipeline & Feature Engine")
    print("-" * 60)
    
    test_coin = pool_mixed[0] if pool_mixed else "BTCUSDT"
    print(f"Fetching full pipeline data for: {test_coin}...")
    try:
        df = fetch_klines(test_coin, interval=config.TIMEFRAME_EXECUTION, limit=100)
        df_feat = compute_hmm_features(df)
        live_price = get_current_price(test_coin)
        rsi = df_feat['rsi'].iloc[-1] if 'rsi' in df_feat.columns else 0

        print(f"✅ Data for {test_coin} successfully fetched and features computed!")
        print(f"   - Rows: {len(df_feat)}")
        print(f"   - Live Price: {live_price}")
        print(f"   - RSI: {rsi:.2f}")
        print("\nLast 2 rows of computed DataFrame:")
        columns_to_show = ['open', 'high', 'low', 'close', 'volume', 'log_return', 'volatility', 'rsi']
        actual_cols = [c for c in columns_to_show if c in df_feat.columns]
        print(df_feat[actual_cols].tail(2))
    except Exception as e:
        print(f"❌ Error fetching data for {test_coin}: {e}")

    print("\n======================= VERIFICATION COMPLETE =======================")

if __name__ == "__main__":
    main()
