'use client';

import Link from 'next/link';
import { Header } from '@/components/header';
import { Check, Sparkles, Clock, Zap, Shield, Crown } from 'lucide-react';
import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';

interface Feature {
  text: string;
  comingSoon?: boolean;
}

interface Plan {
  tier: string;
  icon: string;
  name: string;
  price: string;
  priceUSD?: string;
  period: string;
  annualPrice?: string;
  trial?: string;
  tagline: string;
  coinScans: string;
  features: Feature[];
  cta: string;
  href: string;
  popular: boolean;
  gradient: string;
  accentColor: string;
}

export default function PricingPage() {
  const [mounted, setMounted] = useState(false);
  const [annual, setAnnual] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  const plans: Plan[] = [
    {
      tier: 'EXPLORER',
      icon: '🔍',
      name: 'Explorer',
      price: 'Free',
      period: 'forever',
      tagline: 'See the magic before you commit',
      coinScans: '3 coin scans',
      features: [
        { text: 'Paper trading mode' },
        { text: '3 coins scanned per cycle' },
        { text: 'Dashboard (read-only)' },
        { text: 'Athena signals (1hr delayed)' },
        { text: 'Basic regime detection' },
      ],
      cta: 'Start Free',
      href: '/dashboard',
      popular: false,
      gradient: 'linear-gradient(135deg, rgba(107,114,128,0.15), rgba(75,85,99,0.08))',
      accentColor: '#6B7280',
    },
    {
      tier: 'STARTER',
      icon: '💎',
      name: 'Starter',
      price: annual ? '₹3,920' : '₹3,999',
      priceUSD: annual ? '~$47' : '~$49',
      period: annual ? 'per month (billed annually)' : 'per month',
      annualPrice: annual ? '₹47,000/yr — save ₹950' : undefined,
      trial: '14-day free trial',
      tagline: 'For serious retail traders',
      coinScans: '15 coin scans',
      features: [
        { text: '15 coins scanned (full universe)' },
        { text: 'Live trading (Binance)' },
        { text: 'Real-time Athena AI signals' },
        { text: 'Full P&L dashboard' },
        { text: 'Telegram alerts' },
        { text: '3 active positions max' },
        { text: 'HMM regime detection' },
      ],
      cta: 'Start 14-Day Trial',
      href: '/signup?plan=starter',
      popular: false,
      gradient: 'linear-gradient(135deg, rgba(6,182,212,0.12), rgba(59,130,246,0.06))',
      accentColor: '#06B6D4',
    },
    {
      tier: 'PRO',
      icon: '🏛️',
      name: 'Pro',
      price: annual ? '₹11,920' : '₹11,999',
      priceUSD: annual ? '~$143' : '~$149',
      period: annual ? 'per month (billed annually)' : 'per month',
      annualPrice: annual ? '₹1,43,000/yr — save ₹24,000' : undefined,
      trial: '14-day free trial',
      tagline: 'For power users — our most popular plan',
      coinScans: '30+ coin scans',
      features: [
        { text: 'Unlimited active positions' },
        { text: 'Binance + CoinDCX exchanges' },
        { text: 'Multi-agent analysis (AI + Web3)', comingSoon: true },
        { text: 'VC Wallet Tracking alerts', comingSoon: true },
        { text: 'Narrative Rotation Tracker', comingSoon: true },
        { text: 'Copy-bot access', comingSoon: true },
        { text: 'Athena signals + full history' },
        { text: 'Email + Telegram + Webhook alerts' },
        { text: 'Advanced P&L charts & export' },
        { text: 'Priority support (24hr)' },
      ],
      cta: 'Start 14-Day Trial',
      href: '/signup?plan=pro',
      popular: true,
      gradient: 'linear-gradient(135deg, rgba(139,92,246,0.15), rgba(59,130,246,0.08))',
      accentColor: '#A78BFA',
    },
    {
      tier: 'INSTITUTIONAL',
      icon: '🏢',
      name: 'Institutional',
      price: annual ? '₹39,920' : '₹39,999',
      priceUSD: annual ? '~$479' : '~$499',
      period: annual ? 'per month (billed annually)' : 'per month',
      annualPrice: annual ? '₹4,79,000/yr — save ₹80,000' : undefined,
      tagline: 'For funds, prop desks & whales',
      coinScans: '50+ coin scans',
      features: [
        { text: 'Everything in Pro' },
        { text: 'Custom coin universe (50+)' },
        { text: 'REST + WebSocket API access', comingSoon: true },
        { text: 'Auto-rebalancing (Kelly Criterion)', comingSoon: true },
        { text: 'Custom agent configurations', comingSoon: true },
        { text: 'White-label option', comingSoon: true },
        { text: '99.5% uptime SLA' },
        { text: 'Weekly 1:1 strategy call' },
        { text: 'Performance fee option (10% of alpha)', comingSoon: true },
      ],
      cta: 'Contact Sales',
      href: 'mailto:hello@synapticbots.com?subject=Institutional%20Plan',
      popular: false,
      gradient: 'linear-gradient(135deg, rgba(245,158,11,0.12), rgba(234,179,8,0.06))',
      accentColor: '#F59E0B',
    },
  ];

  return (
    <div className="min-h-screen">
      <Header />

      <section className="pt-32 pb-20 px-4">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-center mb-12"
          >
            <h1 style={{ fontSize: '48px', fontWeight: 800, marginBottom: '12px' }}>
              Choose Your <span className="text-gradient">Trading Edge</span>
            </h1>
            <p style={{ fontSize: '18px', color: '#9CA3AF', maxWidth: '600px', margin: '0 auto 24px' }}>
              AI-powered crypto intelligence. Start with a 14-day free trial.
            </p>

            {/* Annual / Monthly Toggle */}
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: '12px',
              background: 'rgba(17,24,39,0.8)', padding: '6px 20px', borderRadius: '40px',
              border: '1px solid rgba(255,255,255,0.08)',
            }}>
              <span style={{ fontSize: '14px', color: annual ? '#6B7280' : '#F9FAFB', fontWeight: 600, cursor: 'pointer' }}
                onClick={() => setAnnual(false)}>Monthly</span>
              <div
                onClick={() => setAnnual(!annual)}
                style={{
                  width: '44px', height: '24px', borderRadius: '12px', cursor: 'pointer',
                  background: annual ? 'var(--color-primary)' : 'rgba(255,255,255,0.15)',
                  position: 'relative', transition: 'background 0.3s',
                }}
              >
                <div style={{
                  width: '18px', height: '18px', borderRadius: '50%', background: '#fff',
                  position: 'absolute', top: '3px', transition: 'left 0.3s',
                  left: annual ? '23px' : '3px',
                }} />
              </div>
              <span style={{ fontSize: '14px', color: annual ? '#F9FAFB' : '#6B7280', fontWeight: 600, cursor: 'pointer' }}
                onClick={() => setAnnual(true)}>
                Annual <span style={{ fontSize: '11px', color: '#10B981', fontWeight: 700, marginLeft: '4px' }}>Save 2 months</span>
              </span>
            </div>
          </motion.div>

          {/* Cards Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px' }}>
            {plans.map((plan, index) => (
              <motion.div
                key={plan.tier}
                initial={{ opacity: 0, y: 30 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.1 }}
                style={{
                  background: plan.gradient,
                  border: plan.popular ? `2px solid ${plan.accentColor}` : '1px solid rgba(255,255,255,0.08)',
                  borderRadius: '20px',
                  padding: '28px 24px',
                  position: 'relative',
                  display: 'flex', flexDirection: 'column',
                  boxShadow: plan.popular ? `0 0 40px ${plan.accentColor}22` : 'none',
                  transition: 'transform 0.2s, box-shadow 0.2s',
                }}
                className="hover-lift"
              >
                {/* Popular Badge */}
                {plan.popular && (
                  <div style={{
                    position: 'absolute', top: '-14px', left: '50%', transform: 'translateX(-50%)',
                    padding: '4px 16px', borderRadius: '20px', fontSize: '12px', fontWeight: 700,
                    background: plan.accentColor, color: '#0A0E1A',
                    display: 'flex', alignItems: 'center', gap: '4px',
                  }}>
                    <Sparkles style={{ width: '14px', height: '14px' }} />
                    Most Popular
                  </div>
                )}

                {/* 14-Day Trial Badge */}
                {plan.trial && (
                  <div style={{
                    display: 'inline-flex', alignItems: 'center', gap: '4px',
                    fontSize: '11px', fontWeight: 700, color: '#10B981',
                    background: 'rgba(16,185,129,0.1)', padding: '4px 10px', borderRadius: '8px',
                    border: '1px solid rgba(16,185,129,0.2)', marginBottom: '12px', alignSelf: 'flex-start',
                  }}>
                    <Clock style={{ width: '12px', height: '12px' }} />
                    {plan.trial}
                  </div>
                )}

                {/* Plan Header */}
                <div style={{ marginBottom: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                    <span style={{ fontSize: '24px' }}>{plan.icon}</span>
                    <h3 style={{ fontSize: '22px', fontWeight: 800, color: plan.accentColor, margin: 0 }}>{plan.name}</h3>
                  </div>
                  <p style={{ fontSize: '13px', color: '#9CA3AF', margin: '4px 0 12px' }}>{plan.tagline}</p>

                  <div>
                    <span style={{ fontSize: '36px', fontWeight: 800, color: '#F9FAFB' }}>{plan.price}</span>
                    {plan.priceUSD && (
                      <span style={{ fontSize: '14px', color: '#6B7280', marginLeft: '6px' }}>({plan.priceUSD})</span>
                    )}
                    <div style={{ fontSize: '13px', color: '#6B7280' }}>{plan.period}</div>
                    {plan.annualPrice && (
                      <div style={{ fontSize: '11px', color: '#10B981', fontWeight: 600, marginTop: '2px' }}>
                        {plan.annualPrice}
                      </div>
                    )}
                  </div>

                  <div style={{
                    fontSize: '12px', fontWeight: 700, color: '#06B6D4',
                    marginTop: '8px', padding: '4px 10px', borderRadius: '8px',
                    background: 'rgba(6,182,212,0.08)', display: 'inline-block',
                  }}>
                    {plan.coinScans}
                  </div>
                </div>

                {/* Features */}
                <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 20px', flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {plan.features.map((f, idx) => (
                    <li key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                      <Check style={{
                        width: '16px', height: '16px', flexShrink: 0, marginTop: '2px',
                        color: f.comingSoon ? '#4B5563' : '#10B981',
                      }} />
                      <span style={{
                        fontSize: '13px', lineHeight: '1.4',
                        color: f.comingSoon ? '#6B7280' : '#D1D5DB',
                      }}>
                        {f.text}
                        {f.comingSoon && (
                          <span style={{
                            fontSize: '9px', fontWeight: 700, marginLeft: '6px',
                            padding: '2px 6px', borderRadius: '4px',
                            background: 'rgba(245,158,11,0.12)', color: '#F59E0B',
                            verticalAlign: 'middle',
                          }}>
                            COMING SOON
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>

                {/* CTA Button */}
                {plan.href.startsWith('mailto') ? (
                  <a
                    href={plan.href}
                    style={{
                      display: 'block', width: '100%', padding: '14px',
                      borderRadius: '12px', fontSize: '15px', fontWeight: 700,
                      textAlign: 'center', textDecoration: 'none',
                      background: plan.accentColor, color: '#0A0E1A',
                      transition: 'opacity 0.2s',
                    }}
                  >
                    {plan.cta}
                  </a>
                ) : (
                  <Link
                    href={plan.href}
                    style={{
                      display: 'block', width: '100%', padding: '14px',
                      borderRadius: '12px', fontSize: '15px', fontWeight: 700,
                      textAlign: 'center', textDecoration: 'none',
                      background: plan.popular ? plan.accentColor : 'rgba(255,255,255,0.08)',
                      color: plan.popular ? '#0A0E1A' : '#F9FAFB',
                      border: plan.popular ? 'none' : '1px solid rgba(255,255,255,0.12)',
                      transition: 'opacity 0.2s',
                    }}
                  >
                    {plan.cta}
                  </Link>
                )}
              </motion.div>
            ))}
          </div>

          {/* Bottom Trust Section */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5 }}
            style={{
              textAlign: 'center', marginTop: '48px', padding: '24px',
              display: 'flex', justifyContent: 'center', gap: '40px', flexWrap: 'wrap',
            }}
          >
            {[
              { icon: '🔒', text: 'Your API keys stay on your machine' },
              { icon: '⚡', text: 'Cancel anytime — no lock-in' },
              { icon: '🏛️', text: 'Athena AI powered by Gemini' },
              { icon: '📊', text: 'HMM regime detection — unique to Synaptic' },
            ].map((item, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '18px' }}>{item.icon}</span>
                <span style={{ fontSize: '13px', color: '#9CA3AF' }}>{item.text}</span>
              </div>
            ))}
          </motion.div>
        </div>
      </section>

      <footer className="border-t border-[var(--color-surface-light)] py-8 px-4">
        <div className="max-w-7xl mx-auto text-center text-[var(--color-text-secondary)]">
          <p>&copy; 2026 Synaptic Bots. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}