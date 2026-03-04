import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';
import * as fs from 'fs';
import * as path from 'path';

export const dynamic = 'force-dynamic';

const DATA_DIR = path.resolve(process.cwd(), '..', '..', 'data');

function readJSON(filename: string, fallback: any = {}) {
    try {
        const filepath = path.join(DATA_DIR, filename);
        if (fs.existsSync(filepath)) {
            return JSON.parse(fs.readFileSync(filepath, 'utf-8'));
        }
    } catch { /* silent */ }
    return fallback;
}

function writeJSON(filename: string, data: any) {
    try {
        const filepath = path.join(DATA_DIR, filename);
        fs.writeFileSync(filepath, JSON.stringify(data, null, 2));
    } catch (e) {
        console.error('Failed to write', filename, e);
    }
}

export async function POST(request: Request) {
    try {
        const session = await getServerSession(authOptions);
        if (!session?.user) {
            return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
        }

        const { tradeId, symbol } = await request.json();
        if (!tradeId && !symbol) {
            return NextResponse.json({ error: 'tradeId or symbol required' }, { status: 400 });
        }

        const userId = (session.user as any)?.id;
        const isAdmin = (session.user as any)?.role === 'admin';
        const book = readJSON('tradebook.json', { trades: [], summary: {} });
        const trades = book.trades || [];

        // Find target trade(s)
        const targets: any[] = [];
        for (const t of trades) {
            if ((t.status || '').toUpperCase() !== 'ACTIVE') continue;

            // Non-admin can only close their own trades
            if (!isAdmin && t.user_id !== userId) continue;

            if (tradeId && t.trade_id === tradeId) {
                targets.push(t);
                break;
            }
            if (symbol && t.symbol === symbol) {
                targets.push(t);
            }
        }

        if (targets.length === 0) {
            return NextResponse.json({ error: 'No matching active trade found' }, { status: 404 });
        }

        // Close each target at current price
        const closed: any[] = [];
        for (const trade of targets) {
            const currentPrice = trade.current_price || trade.entry_price;
            const entry = trade.entry_price;
            const qty = trade.quantity;
            const lev = trade.leverage;
            const capital = trade.capital;

            let rawPnl: number;
            if (trade.position === 'LONG') {
                rawPnl = (currentPrice - entry) * qty;
            } else {
                rawPnl = (entry - currentPrice) * qty;
            }

            // Commission
            const entryNotional = entry * qty;
            const exitNotional = currentPrice * qty;
            const commission = Math.round((entryNotional + exitNotional) * 0.0005 * 10000) / 10000;
            const fundingCost = trade.funding_cost || 0;

            const isLive = (trade.mode || '').toUpperCase() === 'LIVE';
            let leveragedPnl: number;
            if (isLive) {
                leveragedPnl = Math.round((rawPnl - fundingCost) * 10000) / 10000;
            } else {
                leveragedPnl = Math.round((rawPnl * lev - commission - fundingCost) * 10000) / 10000;
            }
            const pnlPct = capital ? Math.round(leveragedPnl / capital * 100 * 100) / 100 : 0;

            // Calculate duration
            const entryTime = new Date(trade.entry_timestamp);
            const duration = (Date.now() - entryTime.getTime()) / 60000;

            trade.exit_timestamp = new Date().toISOString();
            trade.exit_price = currentPrice;
            trade.current_price = currentPrice;
            trade.status = 'CLOSED';
            trade.exit_reason = 'MANUAL_CLOSE';
            trade.commission = commission;
            trade.realized_pnl = leveragedPnl;
            trade.realized_pnl_pct = pnlPct;
            trade.unrealized_pnl = 0;
            trade.unrealized_pnl_pct = 0;
            trade.duration_minutes = Math.round(duration * 10) / 10;

            closed.push({
                trade_id: trade.trade_id,
                symbol: trade.symbol,
                pnl: leveragedPnl,
                pnl_pct: pnlPct,
            });
        }

        writeJSON('tradebook.json', book);

        return NextResponse.json({ success: true, closed });
    } catch (error: any) {
        console.error('Trade close error:', error);
        return NextResponse.json({ error: 'Failed to close trade' }, { status: 500 });
    }
}
