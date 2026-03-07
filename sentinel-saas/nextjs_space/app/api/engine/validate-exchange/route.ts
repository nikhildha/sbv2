import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';

export const dynamic = 'force-dynamic';

const ENGINE_API_URL = process.env.ENGINE_API_URL || process.env.PYTHON_ENGINE_URL;

/**
 * GET /api/engine/validate-exchange?exchange=coindcx
 *
 * Proxies to engine's /api/validate-exchange.
 * Engine tests its Railway env-var API keys and returns balance.
 * Used by the Deploy Bot modal "Verify Connection" button.
 *
 * Returns: { valid: true, exchange: "coindcx", balance: 1247.5, currency: "USDT" }
 *       or { valid: false, exchange: "coindcx", error: "..." }
 */
export async function GET(req: NextRequest) {
    try {
        const session = await getServerSession(authOptions);
        if (!session?.user) {
            return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
        }

        if (!ENGINE_API_URL) {
            return NextResponse.json({ valid: false, error: 'Engine not configured' });
        }

        const exchange = req.nextUrl.searchParams.get('exchange') || 'coindcx';

        const res = await fetch(
            `${ENGINE_API_URL}/api/validate-exchange?exchange=${encodeURIComponent(exchange)}`,
            { cache: 'no-store', signal: AbortSignal.timeout(10000) }
        );

        const data = await res.json();
        return NextResponse.json(data);
    } catch (err: any) {
        return NextResponse.json({ valid: false, error: String(err) });
    }
}
