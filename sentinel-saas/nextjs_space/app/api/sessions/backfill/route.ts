import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';
import { prisma } from '@/lib/prisma';
import { backfillLegacySession } from '@/lib/bot-session';

export const dynamic = 'force-dynamic';

/**
 * POST /api/sessions/backfill  (admin only)
 * Creates "Session 0 (Legacy)" for every bot that has trades with no sessionId.
 * Run once after deploying the BotSession migration.
 */
export async function POST() {
    try {
        const session = await getServerSession(authOptions);
        if (!session?.user) {
            return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
        }
        if ((session.user as any)?.role !== 'admin') {
            return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
        }

        // Get all bots that have at least one untagged trade
        const botsWithUntagged = await prisma.bot.findMany({
            where: {
                trades: { some: { sessionId: null } },
            },
            include: { config: true },
        });

        let created = 0;
        for (const bot of botsWithUntagged) {
            const mode = bot.config?.mode ?? 'paper';
            const didCreate = await backfillLegacySession(bot.id, mode);
            if (didCreate) created++;
        }

        return NextResponse.json({
            success: true,
            botsProcessed: botsWithUntagged.length,
            sessionsCreated: created,
            message: `Created ${created} legacy session(s) across ${botsWithUntagged.length} bot(s)`,
        });
    } catch (error: any) {
        console.error('[sessions/backfill] error:', error);
        return NextResponse.json({ error: 'Backfill failed' }, { status: 500 });
    }
}
