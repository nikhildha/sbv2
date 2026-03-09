/**
 * POST /api/admin/mark-trades-closed
 *
 * Admin-only. Directly marks specific DB trades as closed by exchangeOrderId.
 * Used to clean up orphaned "active" DB trades whose engine records no longer exist.
 *
 * Body: { email: string, exchangeOrderIds: string[] }
 */
import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';
import prisma from '@/lib/prisma';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
    const session = await getServerSession(authOptions);
    if (!session?.user || (session.user as any)?.role !== 'admin') {
        return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
    }

    const { email, exchangeOrderIds } = await request.json().catch(() => ({}));

    if (!email || !Array.isArray(exchangeOrderIds) || exchangeOrderIds.length === 0) {
        return NextResponse.json({ error: 'email and exchangeOrderIds[] required' }, { status: 400 });
    }

    // Resolve userId from email
    const user = await prisma.user.findUnique({
        where: { email: String(email) },
        select: { id: true },
    });
    if (!user) {
        return NextResponse.json({ error: `User not found: ${email}` }, { status: 404 });
    }

    // Update matching trades to closed — scoped to user's bots for safety
    const result = await prisma.trade.updateMany({
        where: {
            exchangeOrderId: { in: exchangeOrderIds.map(String) },
            bot: { userId: user.id },
            status: { in: ['active', 'ACTIVE', 'Active'] },
        },
        data: {
            status: 'closed',
            exitTime: new Date(),
            exitReason: 'ADMIN_ORPHAN_CLOSE',
            activePnl: 0,
            activePnlPercent: 0,
        },
    });

    return NextResponse.json({
        success: true,
        closed: result.count,
        email,
        exchangeOrderIds,
    });
}
