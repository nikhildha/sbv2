'use client';

/**
 * Athena Intelligence Panel — compact dashboard widget showing LLM reasoning decisions.
 * Displays recent EXECUTE/REDUCE_SIZE/VETO decisions from the Athena brain.
 */

interface AthenaDecision {
    symbol: string;
    time: string;
    side?: string;
    conviction?: number;
    action: string;
    adjusted_confidence: number;
    reasoning: string;
    risk_flags: string[];
    model: string;
    latency_ms: number;
}

interface AthenaState {
    enabled: boolean;
    model?: string;
    initialized?: boolean;
    cycle_calls?: number;
    cache_size?: number;
    recent_decisions?: AthenaDecision[];
}

interface Props {
    athena: AthenaState;
    coinStates?: Record<string, any>;
}

const ACTION_STYLES: Record<string, { bg: string; border: string; text: string; icon: string; label: string }> = {
    EXECUTE: {
        bg: 'rgba(16,185,129,0.08)',
        border: 'rgba(16,185,129,0.3)',
        text: '#10B981',
        icon: '✅',
        label: 'EXECUTE',
    },
    REDUCE_SIZE: {
        bg: 'rgba(245,158,11,0.08)',
        border: 'rgba(245,158,11,0.3)',
        text: '#F59E0B',
        icon: '⚠️',
        label: 'REDUCE',
    },
    VETO: {
        bg: 'rgba(239,68,68,0.08)',
        border: 'rgba(239,68,68,0.3)',
        text: '#EF4444',
        icon: '🚫',
        label: 'VETO',
    },
};

function formatTime(iso: string): string {
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
        return '—';
    }
}

export function AthenaPanel({ athena, coinStates }: Props) {
    if (!athena?.enabled) return null;

    const decisions = athena.recent_decisions || [];

    // Also scan coin_states for athena actions (from latest cycle)
    const athenaCoins = Object.entries(coinStates || {})
        .filter(([, c]: [string, any]) => c.athena || (c.action || '').startsWith('ATHENA_'))
        .map(([sym, c]: [string, any]) => ({
            symbol: sym,
            action: c.action?.startsWith('ATHENA_VETO') ? 'VETO' : (c.athena || 'EXECUTE'),
            detail: c.action?.startsWith('ATHENA_VETO') ? c.action.replace('ATHENA_VETO:', '') : '',
        }));

    const hasData = decisions.length > 0 || athenaCoins.length > 0;

    return (
        <div style={{
            background: 'rgba(17, 24, 39, 0.85)',
            backdropFilter: 'blur(16px)',
            border: '1px solid rgba(139,92,246,0.2)',
            borderRadius: '16px',
            overflow: 'hidden',
        }}>
            {/* Header */}
            <div style={{
                padding: '14px 20px',
                background: 'linear-gradient(135deg, rgba(139,92,246,0.10) 0%, rgba(59,130,246,0.06) 100%)',
                borderBottom: '1px solid rgba(255,255,255,0.06)',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '20px' }}>🏛️</span>
                    <h2 style={{ fontSize: '16px', fontWeight: 700, color: '#A78BFA', margin: 0, letterSpacing: '0.3px' }}>
                        Athena Intelligence
                    </h2>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    {athena.initialized && (
                        <span style={{
                            fontSize: '11px', padding: '2px 8px', borderRadius: '8px',
                            background: 'rgba(16,185,129,0.15)', color: '#10B981', fontWeight: 600,
                        }}>
                            ONLINE
                        </span>
                    )}
                    <span style={{ fontSize: '11px', color: '#6B7280' }}>
                        {athena.model || 'gemini-2.0-flash'}
                    </span>
                    {(athena.cycle_calls ?? 0) > 0 && (
                        <span style={{ fontSize: '11px', color: '#6B7280' }}>
                            {athena.cycle_calls} calls
                        </span>
                    )}
                </div>
            </div>

            {/* Body */}
            <div style={{ padding: '12px 16px', maxHeight: '260px', overflowY: 'auto' }}>
                {!hasData ? (
                    <div style={{ textAlign: 'center', padding: '20px 0', color: '#6B7280', fontSize: '13px' }}>
                        <span style={{ fontSize: '24px', display: 'block', marginBottom: '6px', opacity: 0.5 }}>🏛️</span>
                        Awaiting first scan cycle…
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {/* Recent LLM decisions (from log) */}
                        {decisions.slice(-5).reverse().map((d, i) => {
                            const style = ACTION_STYLES[d.action] || ACTION_STYLES.EXECUTE;
                            return (
                                <div key={`d-${i}`} style={{
                                    display: 'flex', alignItems: 'center', gap: '10px',
                                    padding: '8px 12px', borderRadius: '10px',
                                    background: style.bg, border: `1px solid ${style.border}`,
                                }}>
                                    <span style={{ fontSize: '14px', flexShrink: 0 }}>{style.icon}</span>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                            <span style={{ fontWeight: 700, fontSize: '13px', color: '#E5E7EB' }}>
                                                {d.symbol?.replace('USDT', '')}
                                            </span>
                                            <span style={{
                                                fontSize: '10px', fontWeight: 700, color: style.text,
                                                padding: '1px 6px', borderRadius: '4px',
                                                background: `${style.bg}`,
                                            }}>
                                                {style.label}
                                            </span>
                                            {d.side && (
                                                <span style={{
                                                    fontSize: '10px', fontWeight: 600,
                                                    color: d.side === 'BUY' ? '#10B981' : '#EF4444',
                                                }}>
                                                    {d.side}
                                                </span>
                                            )}
                                            <span style={{ fontSize: '10px', color: '#6B7280', fontFamily: 'monospace' }}>
                                                ×{d.adjusted_confidence.toFixed(2)}
                                            </span>
                                            {d.latency_ms > 0 && (
                                                <span style={{ fontSize: '10px', color: '#4B5563' }}>
                                                    {d.latency_ms}ms
                                                </span>
                                            )}
                                        </div>
                                        <div style={{
                                            fontSize: '11px', color: '#9CA3AF', marginTop: '2px',
                                            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                                        }}>
                                            {d.reasoning}
                                        </div>
                                    </div>
                                    <span style={{ fontSize: '10px', color: '#4B5563', flexShrink: 0 }}>
                                        {formatTime(d.time)}
                                    </span>
                                </div>
                            );
                        })}

                        {/* Coins vetoed in current cycle (from coin_states) */}
                        {athenaCoins.filter(c => c.action === 'VETO').map((c, i) => (
                            <div key={`v-${i}`} style={{
                                display: 'flex', alignItems: 'center', gap: '10px',
                                padding: '6px 12px', borderRadius: '10px',
                                background: 'rgba(239,68,68,0.06)',
                                border: '1px solid rgba(239,68,68,0.15)',
                            }}>
                                <span style={{ fontSize: '14px' }}>🚫</span>
                                <span style={{ fontWeight: 700, fontSize: '12px', color: '#E5E7EB' }}>
                                    {c.symbol.replace('USDT', '')}
                                </span>
                                <span style={{ fontSize: '10px', color: '#EF4444', fontWeight: 600 }}>VETO</span>
                                <span style={{
                                    fontSize: '11px', color: '#9CA3AF', flex: 1,
                                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                                }}>
                                    {c.detail}
                                </span>
                            </div>
                        ))}

                        {/* Risk flags summary */}
                        {decisions.length > 0 && (() => {
                            const allFlags = decisions.flatMap(d => d.risk_flags || []);
                            const unique = [...new Set(allFlags)].slice(0, 5);
                            if (unique.length === 0) return null;
                            return (
                                <div style={{
                                    display: 'flex', flexWrap: 'wrap', gap: '4px',
                                    padding: '4px 0', marginTop: '2px',
                                }}>
                                    {unique.map((flag, i) => (
                                        <span key={i} style={{
                                            fontSize: '10px', padding: '2px 8px', borderRadius: '6px',
                                            background: 'rgba(245,158,11,0.10)', color: '#F59E0B',
                                            border: '1px solid rgba(245,158,11,0.15)',
                                        }}>
                                            ⚡ {flag}
                                        </span>
                                    ))}
                                </div>
                            );
                        })()}
                    </div>
                )}
            </div>
        </div>
    );
}
