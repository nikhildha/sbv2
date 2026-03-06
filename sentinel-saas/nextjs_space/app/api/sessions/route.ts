import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';
import { prisma } from '@/lib/prisma';

export const dynamic = 'force-dynamic';

/**
 * GET /api/sessions
 * Returns all BotSessions for the authenticated user's bots, sorted newest first.
 * For the active session, augments totalPnl with live activePnl from open trades.
 */
export async function GET(request: NextRequest) {
    try {
        const session = await getServerSession(authOptions);
        if (!session?.user) {
            return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
        }

        const userId = (session.user as any).id;
        const { searchParams } = new URL(request.url);
        const botIdFilter = searchParams.get('botId');

        // Fetch all sessions for this user's bots
        const sessions = await prisma.botSession.findMany({
            where: {
                bot: { userId },
                ...(botIdFilter ? { botId: botIdFilter } : {}),
            },
            orderBy: { startedAt: 'desc' },
            include: {
                bot: { select: { name: true, exchange: true } },
            },
        });

        // For active sessions, add live running PnL from open trades
        const enriched = await Promise.all(sessions.map(async (s) => {
            let livePnl = s.totalPnl;
            let liveTotalTrades = s.totalTrades;

            if (s.status === 'active') {
                const openTrades = await prisma.trade.findMany({
                    where: { sessionId: s.id, status: 'active' },
                    select: { activePnl: true, capital: true },
                });
                const activePnl = openTrades.reduce((sum, t) => sum + t.activePnl, 0);
                const activeCapital = openTrades.reduce((sum, t) => sum + t.capital, 0);
                livePnl = s.totalPnl + activePnl;
                liveTotalTrades = s.totalTrades + openTrades.length;

                // Live ROI includes open positions
                const totalCap = s.totalCapital + activeCapital;
                return {
                    ...s,
                    livePnl,
                    liveTotalTrades,
                    liveRoi: totalCap > 0 ? (livePnl / totalCap) * 100 : 0,
                };
            }

            return { ...s, livePnl, liveTotalTrades, liveRoi: s.roi };
        }));

        // All-time summary
        const allTimePnl = enriched.reduce((s, ses) => s + ses.livePnl, 0);
        const allTimeTrades = enriched.reduce((s, ses) => s + ses.liveTotalTrades, 0);
        const allTimeCapital = enriched.reduce((s, ses) => s + ses.totalCapital, 0);
        const allTimeRoi = allTimeCapital > 0 ? (allTimePnl / allTimeCapital) * 100 : 0;
        const bestSession = enriched.reduce((best, ses) =>
            ses.livePnl > (best?.livePnl ?? -Infinity) ? ses : best, enriched[0] ?? null);

        return NextResponse.json({
            sessions: enriched,
            summary: {
                totalSessions: enriched.length,
                allTimePnl,
                allTimeTrades,
                allTimeRoi,
                bestSessionPnl: bestSession?.livePnl ?? 0,
            },
        });
    } catch (error: any) {
        console.error('[sessions] GET error:', error);
        return NextResponse.json({ error: 'Failed to fetch sessions' }, { status: 500 });
    }
}
