import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * GET /api/coindcx/prices
 *
 * Proxies CoinDCX public real-time futures prices (no auth required).
 * Dashboard polls this every 3s for active position price updates.
 *
 * Returns: { "B-BTC_USDT": { ls: 70678.1, fr: -0.00003 }, ... }
 *   ls = last price, fr = funding rate
 */
export async function GET() {
    try {
        const res = await fetch(
            'https://public.coindcx.com/market_data/v3/current_prices/futures/rt',
            { cache: 'no-store', signal: AbortSignal.timeout(4000) }
        );
        if (!res.ok) return NextResponse.json({});
        const data = await res.json();
        return NextResponse.json(data.prices || {});
    } catch {
        return NextResponse.json({});
    }
}
