import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';
import prisma from '@/lib/prisma';

export const dynamic = 'force-dynamic';

/**
 * POST /api/admin/cleanup-trades
 * Removes garbage closed trades with absurd PnL values.
 * These are caused by SL/TP cross-contamination where exit prices
 * from wrong coins generate astronomical fake PnL.
 * 
 * Threshold: any closed trade where |totalPnl| > 5x its capital is garbage.
 */
export async function POST() {
    try {
        const session = await getServerSession(authOptions);
        if (!session?.user || (session.user as any)?.role !== 'admin') {
            return NextResponse.json({ error: 'Admin only' }, { status: 403 });
        }

        // Find all closed trades
        const closedTrades = await prisma.trade.findMany({
            where: { status: 'closed' },
            select: { id: true, coin: true, totalPnl: true, capital: true, totalPnlPercent: true },
        });

        // Identify garbage: |PnL| > 5x capital (e.g., $500+ on a $100 trade)
        const garbageIds: string[] = [];
        const garbageDetails: any[] = [];
        for (const t of closedTrades) {
            const cap = t.capital || 100;
            const pnl = Math.abs(t.totalPnl || 0);
            const pnlPct = Math.abs(t.totalPnlPercent || 0);
            if (pnl > cap * 5 || pnlPct > 500) {
                garbageIds.push(t.id);
                garbageDetails.push({ id: t.id, coin: t.coin, pnl: t.totalPnl, pnlPct: t.totalPnlPercent, capital: t.capital });
            }
        }

        if (garbageIds.length === 0) {
            return NextResponse.json({ message: 'No garbage trades found', cleaned: 0 });
        }

        // Delete garbage trades
        const result = await prisma.trade.deleteMany({
            where: { id: { in: garbageIds } },
        });

        console.log(`[cleanup] Purged ${result.count} garbage trades:`, garbageDetails);

        return NextResponse.json({
            success: true,
            cleaned: result.count,
            details: garbageDetails,
        });
    } catch (error) {
        console.error('[cleanup] Error:', error);
        return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
    }
}

/**
 * GET /api/admin/cleanup-trades
 * Preview garbage trades without deleting.
 */
export async function GET() {
    try {
        const session = await getServerSession(authOptions);
        if (!session?.user || (session.user as any)?.role !== 'admin') {
            return NextResponse.json({ error: 'Admin only' }, { status: 403 });
        }

        const closedTrades = await prisma.trade.findMany({
            where: { status: 'closed' },
            select: { id: true, coin: true, totalPnl: true, capital: true, totalPnlPercent: true, exitReason: true },
        });

        const garbage = closedTrades.filter(t => {
            const cap = t.capital || 100;
            const pnl = Math.abs(t.totalPnl || 0);
            const pnlPct = Math.abs(t.totalPnlPercent || 0);
            return pnl > cap * 5 || pnlPct > 500;
        });

        return NextResponse.json({
            totalClosed: closedTrades.length,
            garbageCount: garbage.length,
            garbage,
        });
    } catch (error) {
        return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
    }
}
