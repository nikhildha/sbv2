/**
 * GET /api/admin/trade-timeline
 *
 * Admin-only audit: shows all bots with their start times and all trades
 * sorted by entryTime. Used to verify multi-user trade attribution is correct
 * even when multiple users deploy bots at different times.
 */
import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';
import prisma from '@/lib/prisma';

export const dynamic = 'force-dynamic';

export async function GET() {
    const session = await getServerSession(authOptions);
    if (!session?.user || (session.user as any)?.role !== 'admin') {
        return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
    }

    // All bots ordered by startedAt
    const bots = await prisma.bot.findMany({
        select: {
            id: true,
            name: true,
            exchange: true,
            isActive: true,
            startedAt: true,
            stoppedAt: true,
            config: { select: { mode: true } },
            user: { select: { email: true } },
            _count: { select: { trades: true } },
        },
        orderBy: { startedAt: 'asc' },
    });

    // All trades ordered by entryTime — include botId for attribution check
    const trades = await prisma.trade.findMany({
        select: {
            id: true,
            coin: true,
            status: true,
            position: true,
            entryTime: true,
            exitTime: true,
            totalPnl: true,
            botId: true,
            exchangeOrderId: true,
            bot: { select: { name: true, user: { select: { email: true } } } },
        },
        orderBy: { entryTime: 'asc' },
        take: 200,
    });

    // For each trade, figure out which bots were ACTIVE at the time it was opened
    // (i.e. had been started but not yet stopped)
    const botsAtTradeTime = trades.map(trade => {
        const t = trade.entryTime ? new Date(trade.entryTime).getTime() : 0;
        const activeBots = bots.filter(b => {
            const started = b.startedAt ? new Date(b.startedAt).getTime() : Infinity;
            const stopped = b.stoppedAt ? new Date(b.stoppedAt).getTime() : Infinity;
            return started <= t && t <= stopped;
        });
        return {
            tradeId: trade.exchangeOrderId || trade.id,
            coin: trade.coin,
            status: trade.status,
            entryTime: trade.entryTime,
            attributedTo: trade.bot?.user?.email || '?',
            botName: trade.bot?.name || '?',
            botId: trade.botId,
            activeBotCount: activeBots.length,
            activeBotsAtTime: activeBots.map(b => ({
                id: b.id,
                name: b.name,
                email: b.user?.email,
            })),
            // Flag: was any OTHER bot also active when this trade was opened?
            multiUserConflict: activeBots.length > 1,
        };
    });

    const conflictCount = botsAtTradeTime.filter(t => t.multiUserConflict).length;

    return NextResponse.json({
        summary: {
            totalBots: bots.length,
            totalTrades: trades.length,
            conflictingTrades: conflictCount,
            note: conflictCount === 0
                ? 'No overlapping bot periods detected — trade attribution is clean'
                : `${conflictCount} trades opened while multiple bots were active — check attribution`,
        },
        bots: bots.map(b => ({
            id: b.id,
            name: b.name,
            email: b.user?.email,
            mode: b.config?.mode,
            exchange: b.exchange,
            isActive: b.isActive,
            startedAt: b.startedAt,
            stoppedAt: b.stoppedAt,
            tradeCount: b._count.trades,
        })),
        trades: botsAtTradeTime,
    });
}
