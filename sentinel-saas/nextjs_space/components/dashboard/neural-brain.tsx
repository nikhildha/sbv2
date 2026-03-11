'use client';

import { useEffect, useRef } from 'react';

interface NeuralBrainProps {
    isOn: boolean;
    cycle?: number;
    color?: string;
}

const CYAN = '#00E5FF';
const AMBER = '#FFB300';
const EMERALD = '#00FF88';

export function NeuralBrain({ isOn, cycle }: NeuralBrainProps) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const animRef = useRef<number>(0);
    const timeRef = useRef<number>(0);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const W = canvas.width = 340;
        const H = canvas.height = 300;
        const cx = W / 2;
        const cy = H / 2 - 10;

        // Neural nodes orbiting the brain sphere
        const NUM_NODES = 28;
        type Node = { theta: number; phi: number; speed: number; color: string };
        const nodes: Node[] = Array.from({ length: NUM_NODES }, (_, i) => ({
            theta: (i / NUM_NODES) * Math.PI * 2,
            phi: (Math.random() * 0.7 + 0.15) * Math.PI,
            speed: (0.003 + Math.random() * 0.004) * (Math.random() > 0.5 ? 1 : -1),
            color: i % 7 === 0 ? AMBER : i % 5 === 0 ? EMERALD : CYAN,
        }));

        // Data flow particles
        type Particle = { t: number; speed: number; fromIdx: number; toIdx: number; color: string };
        const particles: Particle[] = Array.from({ length: 18 }, (_, i) => ({
            t: Math.random(),
            speed: 0.004 + Math.random() * 0.006,
            fromIdx: Math.floor(Math.random() * NUM_NODES),
            toIdx: Math.floor(Math.random() * NUM_NODES),
            color: i % 4 === 0 ? AMBER : CYAN,
        }));

        const project = (theta: number, phi: number, r: number): [number, number, number] => {
            const x = r * Math.sin(phi) * Math.cos(theta);
            const y = r * Math.sin(phi) * Math.sin(theta) * 0.35; // flatten y for 2D projection
            const z = r * Math.cos(phi);
            return [cx + x, cy + y - z * 0.6, z];
        };

        const draw = (t: number) => {
            ctx.clearRect(0, 0, W, H);

            const R = 88; // brain sphere radius

            // ── Outer atmospheric halo ──
            const halo = ctx.createRadialGradient(cx, cy, R * 0.6, cx, cy, R * 2);
            halo.addColorStop(0, 'rgba(0,229,255,0.18)');
            halo.addColorStop(0.4, 'rgba(0,180,255,0.08)');
            halo.addColorStop(0.7, 'rgba(0,120,200,0.04)');
            halo.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.beginPath();
            ctx.arc(cx, cy, R * 2, 0, Math.PI * 2);
            ctx.fillStyle = halo;
            ctx.fill();

            // ── Brain sphere — multi-layer gradient for 3D feel ──
            const sphere = ctx.createRadialGradient(cx - R * 0.28, cy - R * 0.35, R * 0.02, cx, cy, R);
            sphere.addColorStop(0, 'rgba(0,229,255,0.55)');
            sphere.addColorStop(0.25, 'rgba(0,200,255,0.3)');
            sphere.addColorStop(0.55, 'rgba(0,130,200,0.15)');
            sphere.addColorStop(0.85, 'rgba(0,60,120,0.06)');
            sphere.addColorStop(1, 'rgba(0,10,40,0.02)');
            ctx.beginPath();
            ctx.arc(cx, cy, R, 0, Math.PI * 2);
            ctx.fillStyle = sphere;
            ctx.fill();

            // ── Brain outline rim — brighter ──
            const rimGrad = ctx.createLinearGradient(cx - R, cy, cx + R, cy);
            rimGrad.addColorStop(0, 'rgba(0,229,255,0.0)');
            rimGrad.addColorStop(0.25, 'rgba(0,229,255,0.7)');
            rimGrad.addColorStop(0.75, 'rgba(0,229,255,0.7)');
            rimGrad.addColorStop(1, 'rgba(0,229,255,0.0)');
            ctx.beginPath();
            ctx.arc(cx, cy, R, 0, Math.PI * 2);
            ctx.strokeStyle = rimGrad;
            ctx.lineWidth = 2;
            ctx.stroke();

            // ── Extra glowing outer ring ──
            ctx.beginPath();
            ctx.arc(cx, cy, R + 4, 0, Math.PI * 2);
            ctx.strokeStyle = `rgba(0,229,255,${isOn ? 0.18 : 0.05})`;
            ctx.lineWidth = 8;
            ctx.stroke();

            // ── Brain folds (gyri/sulci) — suggest 3D structure ──
            ctx.save();
            ctx.globalAlpha = isOn ? 0.55 : 0.2;
            const foldColor = 'rgba(0,229,255,1)';
            const folds = [
                { x: -30, y: -30, rx: 34, ry: 18, rot: -0.4 },
                { x: 28, y: -35, rx: 32, ry: 16, rot: 0.3 },
                { x: -20, y: 10, rx: 28, ry: 12, rot: -0.2 },
                { x: 25, y: 8, rx: 26, ry: 11, rot: 0.25 },
                { x: 0, y: -45, rx: 22, ry: 10, rot: 0 },
                { x: -40, y: 20, rx: 20, ry: 9, rot: -0.5 },
                { x: 38, y: 22, rx: 20, ry: 9, rot: 0.5 },
                { x: 0, y: 25, rx: 30, ry: 10, rot: 0.1 },
            ];
            folds.forEach(f => {
                ctx.save();
                ctx.translate(cx + f.x, cy + f.y);
                ctx.rotate(f.rot);
                ctx.beginPath();
                ctx.ellipse(0, 0, f.rx, f.ry, 0, 0, Math.PI * 2);
                ctx.strokeStyle = foldColor;
                ctx.lineWidth = 0.8;
                ctx.stroke();
                ctx.restore();
            });
            ctx.restore();

            // ── Brain stem ──
            ctx.save();
            ctx.globalAlpha = isOn ? 0.4 : 0.1;
            ctx.beginPath();
            ctx.moveTo(cx - 12, cy + R * 0.82);
            ctx.bezierCurveTo(cx - 8, cy + R + 15, cx + 8, cy + R + 15, cx + 12, cy + R * 0.82);
            ctx.strokeStyle = 'rgba(0,229,255,0.8)';
            ctx.lineWidth = 2.5;
            ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(cx - 6, cy + R + 14);
            ctx.lineTo(cx - 6, cy + R + 38);
            ctx.moveTo(cx, cy + R + 14);
            ctx.lineTo(cx, cy + R + 40);
            ctx.moveTo(cx + 6, cy + R + 14);
            ctx.lineTo(cx + 6, cy + R + 38);
            ctx.strokeStyle = 'rgba(0,180,255,0.4)';
            ctx.lineWidth = 1.5;
            ctx.stroke();
            ctx.restore();

            // ── Update node positions ──
            nodes.forEach(n => { n.theta += n.speed; });

            // ── Get projected positions ──
            const projected = nodes.map(n => {
                const [px, py, pz] = project(n.theta + t * 0.1, n.phi, R * 1.0);
                return { px, py, pz, color: n.color };
            });

            // ── Draw connection lines from brain surface to nodes ──
            if (isOn) {
                projected.forEach((n, i) => {
                    const brightness = (n.pz + R) / (2 * R); // front = bright
                    if (brightness < 0.15) return; // hide back-facing
                    // line from brain rim toward node
                    const angle = Math.atan2(n.py - cy, n.px - cx);
                    const rimX = cx + Math.cos(angle) * R;
                    const rimY = cy + Math.sin(angle) * R * 0.75;
                    ctx.beginPath();
                    ctx.moveTo(rimX, rimY);
                    ctx.lineTo(n.px, n.py);
                    const alpha = brightness * 0.4;
                    ctx.strokeStyle = n.color.replace(')', `,${alpha})`).replace('rgb', 'rgba').replace('##', '#');
                    // simple alpha approach
                    ctx.globalAlpha = alpha;
                    ctx.lineWidth = 0.6;
                    ctx.stroke();
                    ctx.globalAlpha = 1;

                    // cross-connections between nearby nodes
                    projected.forEach((m, j) => {
                        if (j <= i) return;
                        const dist = Math.hypot(n.px - m.px, n.py - m.py);
                        if (dist < 55 && brightness > 0.3) {
                            ctx.beginPath();
                            ctx.moveTo(n.px, n.py);
                            ctx.lineTo(m.px, m.py);
                            ctx.globalAlpha = (1 - dist / 55) * brightness * 0.15;
                            ctx.strokeStyle = CYAN;
                            ctx.lineWidth = 0.5;
                            ctx.stroke();
                            ctx.globalAlpha = 1;
                        }
                    });
                });

                // ── Draw orbital nodes ──
                projected.forEach(n => {
                    const brightness = (n.pz + R) / (2 * R);
                    if (brightness < 0.2) return;
                    const size = 2.5 + brightness * 2.5;
                    // glow
                    const glow = ctx.createRadialGradient(n.px, n.py, 0, n.px, n.py, size * 3);
                    glow.addColorStop(0, n.color.replace(')', ',0.6)').replace('rgb', 'rgba'));
                    glow.addColorStop(1, n.color.replace(')', ',0)').replace('rgb', 'rgba'));
                    ctx.beginPath();
                    ctx.arc(n.px, n.py, size * 3, 0, Math.PI * 2);
                    ctx.fillStyle = glow;
                    ctx.fill();
                    // core dot
                    ctx.beginPath();
                    ctx.arc(n.px, n.py, size * 0.7, 0, Math.PI * 2);
                    ctx.fillStyle = n.color;
                    ctx.globalAlpha = brightness;
                    ctx.fill();
                    ctx.globalAlpha = 1;
                });

                // ── Draw flowing particles ──
                particles.forEach(p => {
                    p.t = (p.t + p.speed) % 1;
                    const from = projected[p.fromIdx];
                    const to = projected[p.toIdx];
                    if (!from || !to) return;
                    const fx = from.px + (to.px - from.px) * p.t;
                    const fy = from.py + (to.py - from.py) * p.t;
                    // fade in/out
                    const alpha = p.t < 0.1 ? p.t / 0.1 : p.t > 0.9 ? (1 - p.t) / 0.1 : 1;
                    ctx.beginPath();
                    ctx.arc(fx, fy, 2.5, 0, Math.PI * 2);
                    ctx.fillStyle = p.color;
                    ctx.globalAlpha = alpha * 0.9;
                    ctx.fill();
                    ctx.globalAlpha = 1;
                });
            }

            // ── Center inner core glow (always visible) ──
            const coreGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.6);
            coreGlow.addColorStop(0, `rgba(0,229,255,${isOn ? 0.4 : 0.1})`);
            coreGlow.addColorStop(0.4, `rgba(0,160,220,${isOn ? 0.2 : 0.05})`);
            coreGlow.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.beginPath();
            ctx.arc(cx, cy, R * 0.6, 0, Math.PI * 2);
            ctx.fillStyle = coreGlow;
            ctx.fill();

            // ── Pulse ring animation ──
            if (isOn) {
                const pulseAmt = Math.sin(t * 2.5);
                const pulseR = R * 0.75 + pulseAmt * R * 0.15;
                ctx.beginPath();
                ctx.arc(cx, cy, pulseR, 0, Math.PI * 2);
                ctx.strokeStyle = `rgba(0,229,255,${0.12 + pulseAmt * 0.08})`;
                ctx.lineWidth = 18;
                ctx.stroke();
            }

            timeRef.current = t;
        };

        let startTime = 0;
        const animate = (ts: number) => {
            if (!startTime) startTime = ts;
            const t = (ts - startTime) / 1000;
            draw(t);
            animRef.current = requestAnimationFrame(animate);
        };

        animRef.current = requestAnimationFrame(animate);
        return () => cancelAnimationFrame(animRef.current);
    }, [isOn]);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', position: 'relative' }}>
            {/* Title */}
            <div style={{
                fontSize: 11, fontWeight: 900, letterSpacing: '3.5px',
                textTransform: 'uppercase', color: AMBER,
                textShadow: `0 0 12px rgba(255,179,0,0.7)`,
                marginBottom: 0, fontFamily: 'var(--font-ui)',
                position: 'absolute', top: 0, zIndex: 10,
            }}>
                Synaptic Core Brain
            </div>

            {isOn && cycle !== undefined && (
                <div style={{
                    fontSize: 10, color: 'rgba(0,229,255,0.5)', marginTop: 16,
                    fontFamily: 'var(--font-mono)', letterSpacing: '0.5px',
                    position: 'absolute', top: 14, zIndex: 10,
                }}>
                    Cycle #{cycle} · <span style={{ color: 'rgba(0,255,136,0.7)' }}>ACTIVE</span>
                </div>
            )}

            <canvas
                ref={canvasRef}
                style={{
                    display: 'block',
                    filter: isOn ? 'drop-shadow(0 0 24px rgba(0,229,255,0.35))' : 'none',
                    marginTop: 10,
                }}
            />
        </div>
    );
}
