import { getServerSession } from 'next-auth';
import { redirect } from 'next/navigation';
import { authOptions } from '@/lib/auth-options';
import { prisma } from '@/lib/prisma';
import { getActiveBotSession } from '@/lib/bot-session';
import { PerformanceClient } from './performance-client';

export const dynamic = 'force-dynamic';

export default async function PerformancePage() {
    const session = await getServerSession(authOptions);
    if (!session?.user) redirect('/login');

    const userId = (session.user as any)?.id;

    // Get all bots for this user
    const userBots = await prisma.bot.findMany({
        where: { userId },
        select: { id: true, name: true },
    });
    const botIds = userBots.map(b => b.id);

    // Fetch all sessions
    const sessions = await prisma.botSession.findMany({
        where: { botId: { in: botIds } },
        orderBy: { startedAt: 'desc' },
        include: { bot: { select: { name: true, exchange: true } } },
    });

    // Enrich active sessions with live open-trade PnL
    const enriched = await Promise.all(sessions.map(async (s) => {
        if (s.status !== 'active') return { ...s, livePnl: s.totalPnl, liveRoi: s.roi, openTrades: 0 };

        const openTrades = await prisma.trade.findMany({
            where: { sessionId: s.id, status: 'active' },
            select: { activePnl: true, capital: true },
        });
        const activePnl = openTrades.reduce((sum, t) => sum + t.activePnl, 0);
        const activeCapital = openTrades.reduce((sum, t) => sum + t.capital, 0);
        const livePnl = s.totalPnl + activePnl;
        const totalCap = s.totalCapital + activeCapital;
        return {
            ...s,
            livePnl,
            liveRoi: totalCap > 0 ? (livePnl / totalCap) * 100 : 0,
            openTrades: openTrades.length,
        };
    }));

    // All-time summary
    const allTimePnl = enriched.reduce((s, ses) => s + ses.livePnl, 0);
    const allTimeTrades = enriched.reduce((s, ses) => s + ses.totalTrades, 0);
    const allTimeCapital = enriched.reduce((s, ses) => s + ses.totalCapital, 0);
    const allTimeRoi = allTimeCapital > 0 ? (allTimePnl / allTimeCapital) * 100 : 0;
    const bestSession = enriched.reduce(
        (best, ses) => ses.livePnl > (best?.livePnl ?? -Infinity) ? ses : best,
        enriched[0] ?? null
    );

    // Active session id for dashboard context
    const activeBot = userBots[0];
    const activeSession = activeBot ? await getActiveBotSession(activeBot.id) : null;

    return (
        <PerformanceClient
            sessions={enriched as any}
            summary={{
                totalSessions: enriched.length,
                allTimePnl,
                allTimeTrades,
                allTimeRoi,
                bestSessionPnl: bestSession?.livePnl ?? 0,
            }}
            activeSessionId={activeSession?.id ?? null}
        />
    );
}
