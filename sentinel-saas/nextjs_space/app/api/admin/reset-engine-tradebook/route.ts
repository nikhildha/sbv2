import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';
import { getEngineUrl } from '@/lib/engine-url';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const isAdmin = (session.user as any)?.role === 'admin';
    if (!isAdmin) {
      return NextResponse.json({ error: 'Admin only' }, { status: 403 });
    }

    const { mode } = await request.json().catch(() => ({ mode: 'paper' }));
    const engineUrl = getEngineUrl(mode === 'live' ? 'live' : 'paper');

    if (!engineUrl) {
      return NextResponse.json({ error: `No engine URL configured for mode: ${mode}` }, { status: 400 });
    }

    const res = await fetch(`${engineUrl}/api/reset-trades`, {
      method: 'POST',
      signal: AbortSignal.timeout(10000),
    });

    const data = await res.json().catch(() => ({}));
    console.log(`[reset-engine-tradebook] mode=${mode} → engine response:`, data);

    return NextResponse.json({ success: true, mode, engine: data });
  } catch (error: any) {
    console.error('[reset-engine-tradebook] Error:', error);
    return NextResponse.json({ error: error.message || 'Failed' }, { status: 500 });
  }
}
