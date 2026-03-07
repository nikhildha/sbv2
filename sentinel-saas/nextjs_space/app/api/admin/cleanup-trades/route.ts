import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';
import { prisma } from '@/lib/prisma';

export const dynamic = 'force-dynamic';

/**
 * POST /api/admin/cleanup-trades
 * Admin-only: delete all stale trades from Prisma DB.
 * After engine tradebook reset, this ensures the Prisma DB is also clean.
 */
export async function POST() {
    try {
        const session = await getServerSession(authOptions);
        const role = (session?.user as any)?.role;
        if (!session?.user || role !== 'admin') {
            return NextResponse.json({ error: 'Admin only' }, { status: 403 });
        }

        // Count before
        const before = await prisma.trade.count();

        // Get all bots and their trade counts
        const bots = await prisma.bot.findMany({
            select: { id: true, name: true, userId: true },
        });
        const breakdown: Record<string, number> = {};
        for (const bot of bots) {
            const count = await prisma.trade.count({ where: { botId: bot.id } });
            if (count > 0) {
                breakdown[`${bot.name} (${bot.userId.substring(0, 8)})`] = count;
            }
        }

        // Delete ALL trades
        const result = await prisma.trade.deleteMany({});

        return NextResponse.json({
            success: true,
            deletedCount: result.count,
            beforeCount: before,
            breakdown,
            message: `Deleted ${result.count} trades. Fresh sync will import current engine trades on next page load.`,
        });
    } catch (err) {
        console.error('[cleanup-trades]', err);
        return NextResponse.json({ error: String(err) }, { status: 500 });
    }
}
