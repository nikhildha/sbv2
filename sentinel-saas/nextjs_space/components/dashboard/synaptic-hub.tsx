'use client';

import { motion } from 'framer-motion';
import { NeuralBrain } from './neural-brain';

interface SynapticHubProps {
    isOn: boolean;
    cycle?: number;
}

const LEFT_PATH = 'M 100 150 Q 20 140, -160 130';
const RIGHT_PATH = 'M 100 150 Q 180 140, 360 130';
const LEFT_PATH2 = 'M 100 170 Q 30 185, -160 190';
const RIGHT_PATH2 = 'M 100 170 Q 170 185, 360 190';

const PULSE_CSS = `
@keyframes pulseLeft  { from { offset-distance: 0%; opacity: 0; } 10% { opacity: 0.9; } 90% { opacity: 0.9; } to { offset-distance: 100%; opacity: 0; } }
@keyframes pulseRight { from { offset-distance: 0%; opacity: 0; } 10% { opacity: 0.9; } 90% { opacity: 0.9; } to { offset-distance: 100%; opacity: 0; } }
@keyframes pulseLeft2  { from { offset-distance: 0%; opacity: 0; } 15% { opacity: 0.6; } 85% { opacity: 0.6; } to { offset-distance: 100%; opacity: 0; } }
@keyframes pulseRight2 { from { offset-distance: 0%; opacity: 0; } 15% { opacity: 0.6; } 85% { opacity: 0.6; } to { offset-distance: 100%; opacity: 0; } }
@keyframes pulseRing   { from { r: 5px; opacity: 0.7; } to   { r: 85px; opacity: 0; } }

.syn-pulse-left  { offset-path: path('${LEFT_PATH}');  animation: pulseLeft  2.2s linear infinite; }
.syn-pulse-left2 { offset-path: path('${LEFT_PATH2}'); animation: pulseLeft2 3.0s linear infinite; }
.syn-pulse-right { offset-path: path('${RIGHT_PATH}'); animation: pulseRight 2.2s linear infinite; }
.syn-pulse-right2{ offset-path: path('${RIGHT_PATH2}');animation: pulseRight2 3.0s linear infinite; }
`;

export function SynapticHub({ isOn, cycle }: SynapticHubProps) {
    return (
        <div style={{
            position: 'relative',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: 150,
        }}>
            {/* Inject CSS keyframes */}
            <style>{PULSE_CSS}</style>

            {/* ── Breathing atmospheric glow ── */}
            <motion.div
                animate={isOn
                    ? { scale: [1, 1.22, 1], opacity: [0.18, 0.45, 0.18] }
                    : { opacity: 0.06 }
                }
                transition={{ duration: 3.5, repeat: Infinity, ease: 'easeInOut' }}
                style={{
                    position: 'absolute',
                    width: 260,
                    height: 260,
                    borderRadius: '50%',
                    background: 'radial-gradient(circle, rgba(0,229,255,0.38) 0%, rgba(0,120,200,0.08) 50%, transparent 70%)',
                    filter: 'blur(32px)',
                    pointerEvents: 'none',
                    zIndex: 0,
                }}
            />

            {/* ── SVG connection network — overflow:visible reaches sibling cards ── */}
            <svg
                width={200}
                height={320}
                viewBox="0 0 200 320"
                style={{
                    position: 'absolute',
                    top: '50%',
                    left: '50%',
                    transform: 'translate(-50%, -50%)',
                    overflow: 'visible',
                    pointerEvents: 'none',
                    zIndex: 2,
                }}
            >
                <defs>
                    <linearGradient id="lgLeft" x1="1" y1="0" x2="0" y2="0">
                        <stop offset="0%" stopColor="#00E5FF" stopOpacity={isOn ? 0.7 : 0.15} />
                        <stop offset="100%" stopColor="#00E5FF" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="lgRight" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="#00E5FF" stopOpacity={isOn ? 0.7 : 0.15} />
                        <stop offset="100%" stopColor="#00E5FF" stopOpacity={0} />
                    </linearGradient>
                    <filter id="syn-glow">
                        <feGaussianBlur stdDeviation="2" result="b" />
                        <feComposite in="SourceGraphic" in2="b" operator="over" />
                    </filter>
                </defs>

                {/* Static dashed guide lines */}
                <path d={LEFT_PATH} fill="none" stroke="rgba(0,229,255,0.1)" strokeWidth={1} strokeDasharray="4 8" />
                <path d={RIGHT_PATH} fill="none" stroke="rgba(0,229,255,0.1)" strokeWidth={1} strokeDasharray="4 8" />
                <path d={LEFT_PATH2} fill="none" stroke="rgba(0,229,255,0.05)" strokeWidth={0.8} strokeDasharray="3 14" />
                <path d={RIGHT_PATH2} fill="none" stroke="rgba(0,229,255,0.05)" strokeWidth={0.8} strokeDasharray="3 14" />

                {/* Glowing gradient lines (visible when on) */}
                {isOn && (
                    <>
                        <path d={LEFT_PATH} fill="none" stroke="url(#lgLeft)" strokeWidth={1.5} />
                        <path d={RIGHT_PATH} fill="none" stroke="url(#lgRight)" strokeWidth={1.5} />

                        {/* Expanding pulse rings from brain center */}
                        {[0, 1.25, 2.5].map((delay, i) => (
                            <motion.circle
                                key={i}
                                cx={100} cy={150}
                                fill="none"
                                stroke="rgba(0,229,255,0.5)"
                                strokeWidth={1.2}
                                initial={{ r: 8, opacity: 0.6 } as any}
                                animate={{ r: 90, opacity: 0 } as any}
                                transition={{ duration: 2.5, repeat: Infinity, delay, ease: 'easeOut' }}
                            />
                        ))}

                        {/* Data particles — LEFT (cyan toward RegimeCard) */}
                        {[0, 0.9, 1.9].map((delay, i) => (
                            <circle
                                key={`lp${i}`}
                                r={3}
                                fill="#00E5FF"
                                filter="url(#syn-glow)"
                                className="syn-pulse-left"
                                style={{ animationDelay: `${delay}s` }}
                            />
                        ))}

                        {/* Data particles — RIGHT (green toward PnlCard) */}
                        {[0.4, 1.3, 2.3].map((delay, i) => (
                            <circle
                                key={`rp${i}`}
                                r={3}
                                fill="#00FF88"
                                filter="url(#syn-glow)"
                                className="syn-pulse-right"
                                style={{ animationDelay: `${delay}s` }}
                            />
                        ))}

                        {/* Secondary branch particles (amber) */}
                        <circle r={2} fill="#FFB300" filter="url(#syn-glow)"
                            className="syn-pulse-left2" style={{ animationDelay: '0.5s' }} />
                        <circle r={2} fill="#FFB300" filter="url(#syn-glow)"
                            className="syn-pulse-right2" style={{ animationDelay: '1.8s' }} />
                    </>
                )}

                {/* Brain center dot (always) */}
                <circle cx={100} cy={150} r={4} fill="rgba(0,229,255,0.4)" />
            </svg>

            {/* ── Brain canvas sits on top ── */}
            <div style={{ position: 'relative', zIndex: 5 }}>
                <NeuralBrain isOn={isOn} cycle={cycle} />
            </div>
        </div>
    );
}
