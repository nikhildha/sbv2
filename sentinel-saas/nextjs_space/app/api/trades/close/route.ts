import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/lib/auth-options';
import { prisma } from '@/lib/prisma';
import * as fs from 'fs';
import * as path from 'path';

export const dynamic = 'force-dynamic';

const ENGINE_API_URL = process.env.ENGINE_API_URL;

export async function POST(request: Request) {
    try {
        const session = await getServerSession(authOptions);
        if (!session?.user) {
            return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
        }

        const { tradeId: rawTradeId, symbol: rawSymbol } = await request.json();
        if (!rawTradeId && !rawSymbol) {
            return NextResponse.json({ error: 'tradeId or symbol required' }, { status: 400 });
        }

        const userId = (session.user as any)?.id;
        const isAdmin = (session.user as any)?.role === 'admin';

        // ─── Parse composite IDs (e.g. "T-0030-BTCUSDT" → tradeId="T-0030", symbol="BTCUSDT") ──
        let tradeId = rawTradeId;
        let symbol = rawSymbol;
        if (tradeId && tradeId.match(/^T-\d+-\w+/)) {
            const parts = tradeId.match(/^(T-\d+)-(.+)$/);
            if (parts) {
                tradeId = parts[1];
                symbol = symbol || parts[2];
            }
        }

        // ─── Find the trade in Prisma ────────────────────────────────────
        let trade = null;
        const activeStatuses = ['active', 'ACTIVE', 'Active'];

        if (tradeId) {
            // Try direct ID match first
            trade = await prisma.trade.findFirst({
                where: {
                    id: tradeId,
                    status: { in: activeStatuses },
                    bot: isAdmin ? {} : { userId },
                },
                include: { bot: true },
            });

            // Fallback: match by exchangeOrderId (engine trade_id)
            if (!trade) {
                trade = await prisma.trade.findFirst({
                    where: {
                        exchangeOrderId: tradeId,
                        status: { in: activeStatuses },
                        bot: isAdmin ? {} : { userId },
                    },
                    include: { bot: true },
                });
            }

            // Fallback: partial match (trade IDs from frontend may be engine_XXX_botId)
            if (!trade) {
                trade = await prisma.trade.findFirst({
                    where: {
                        id: { contains: tradeId },
                        status: { in: activeStatuses },
                        bot: isAdmin ? {} : { userId },
                    },
                    include: { bot: true },
                });
            }
        }

        if (!trade && symbol) {
            trade = await prisma.trade.findFirst({
                where: {
                    coin: symbol.toUpperCase(),
                    status: { in: activeStatuses },
                    bot: isAdmin ? {} : { userId },
                },
                include: { bot: true },
                orderBy: { entryTime: 'desc' },
            });
        }

        // ─── Fallback: close via engine or local tradebook.json ─────────
        if (!trade) {
            // Try engine API first (production)
            if (ENGINE_API_URL) {
                try {
                    const engineRes = await fetch(`${ENGINE_API_URL}/api/close-trade`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ trade_id: tradeId, symbol }),
                        signal: AbortSignal.timeout(10000),
                    });
                    if (engineRes.ok) {
                        const engineData = await engineRes.json();
                        return NextResponse.json({
                            success: true, source: 'engine',
                            closed: engineData.closed || [{ trade_id: tradeId, symbol }],
                        });
                    }
                } catch { /* fall through to local */ }
            }

            // Local dev fallback: close directly in tradebook.json
            const dataDir = path.resolve(process.cwd(), '..', '..', 'data');
            const tbPath = path.join(dataDir, 'tradebook.json');
            if (fs.existsSync(tbPath)) {
                try {
                    const tbData = JSON.parse(fs.readFileSync(tbPath, 'utf-8'));
                    const allTrades: any[] = tbData.trades || [];

                    // Parse composite IDs like "T-0030-BTCUSDT" → trade_id="T-0030", symbol="BTCUSDT"
                    let searchTradeId = tradeId;
                    let searchSymbol = symbol;
                    if (tradeId && tradeId.match(/^T-\d+-\w+/)) {
                        const parts = tradeId.match(/^(T-\d+)-(.+)$/);
                        if (parts) {
                            searchTradeId = parts[1];
                            searchSymbol = searchSymbol || parts[2];
                        }
                    }

                    const idx = allTrades.findIndex((t: any) => {
                        const tid = t.trade_id || t.id || '';
                        const sym = t.symbol || t.coin || '';
                        const st = (t.status || '').toUpperCase();
                        if (st !== 'ACTIVE') return false;
                        // Match by both trade_id AND symbol for exact identification
                        if (searchTradeId && searchSymbol) {
                            return tid === searchTradeId && sym.toUpperCase() === searchSymbol.toUpperCase();
                        }
                        if (searchTradeId && tid === searchTradeId) return true;
                        if (searchSymbol && sym.toUpperCase() === searchSymbol.toUpperCase()) return true;
                        return false;
                    });

                    if (idx >= 0) {
                        const raw = allTrades[idx];
                        const entry = raw.entry_price || raw.entryPrice || 0;
                        const curPrice = raw.current_price || raw.currentPrice || entry;
                        const cap = raw.capital || raw.position_size || 0;
                        const lev = raw.leverage || 1;
                        const isLong = ['buy', 'long'].includes((raw.side || raw.position || '').toLowerCase());
                        const diff = isLong ? (curPrice - entry) : (entry - curPrice);
                        const pnl = Math.round(diff / entry * lev * cap * 10000) / 10000;
                        const pnlPct = cap > 0 ? Math.round(pnl / cap * 100 * 100) / 100 : 0;

                        allTrades[idx] = {
                            ...raw,
                            status: 'CLOSED',
                            exit_price: curPrice,
                            exit_time: new Date().toISOString(),
                            exit_reason: 'MANUAL_CLOSE',
                            realized_pnl: pnl,
                            realized_pnl_pct: pnlPct,
                        };
                        tbData.trades = allTrades;
                        fs.writeFileSync(tbPath, JSON.stringify(tbData, null, 2));

                        return NextResponse.json({
                            success: true, source: 'tradebook',
                            closed: [{
                                trade_id: raw.trade_id || raw.id,
                                symbol: raw.symbol || raw.coin,
                                pnl, pnl_pct: pnlPct,
                            }],
                        });
                    }
                } catch (err) {
                    console.error('Tradebook JSON close failed:', err);
                }
            }

            return NextResponse.json({ error: 'No matching active trade found' }, { status: 404 });
        }

        // ─── Calculate PNL at current price ──────────────────────────────
        const currentPrice = trade.currentPrice || trade.entryPrice;
        const entry = trade.entryPrice;
        const capital = trade.capital;
        const lev = trade.leverage;
        const isLong = trade.position === 'long';

        const priceDiff = isLong ? (currentPrice - entry) : (entry - currentPrice);
        const rawPnl = priceDiff / entry * lev * capital;
        const leveragedPnl = Math.round(rawPnl * 10000) / 10000;
        const pnlPct = capital > 0 ? Math.round(leveragedPnl / capital * 100 * 100) / 100 : 0;

        // ─── Update trade in Prisma ──────────────────────────────────────
        await prisma.trade.update({
            where: { id: trade.id },
            data: {
                status: 'closed',
                exitPrice: currentPrice,
                exitTime: new Date(),
                exitReason: 'MANUAL_CLOSE',
                totalPnl: leveragedPnl,
                totalPnlPercent: pnlPct,
                activePnl: 0,
                activePnlPercent: 0,
            },
        });

        // ─── Also try to close on engine (best-effort) ───────────────────
        if (ENGINE_API_URL) {
            try {
                const engineTradeId = trade.exchangeOrderId || trade.id;
                await fetch(`${ENGINE_API_URL}/api/close-trade`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        trade_id: engineTradeId,
                        symbol: trade.coin,
                    }),
                    signal: AbortSignal.timeout(5000),
                });
            } catch {
                // Engine close is best-effort — Prisma is source of truth
            }
        }

        return NextResponse.json({
            success: true,
            closed: [{
                trade_id: trade.exchangeOrderId || trade.id,
                symbol: trade.coin,
                pnl: leveragedPnl,
                pnl_pct: pnlPct,
            }],
        });
    } catch (error: any) {
        console.error('Trade close error:', error);
        return NextResponse.json({ error: 'Failed to close trade' }, { status: 500 });
    }
}
