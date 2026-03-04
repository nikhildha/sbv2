// ─── Subscription Tier Limits ───────────────────────────────────────────────
// Central config for feature gating based on subscription tier.

export type TierName = 'free' | 'pro' | 'ultra';

export interface TierLimits {
    maxBots: number;
    coinScans: number;
    exportCSV: boolean;
    intelligencePage: boolean;
    manualClose: boolean;
    apiAccess: boolean;
    label: string;
}

export const TIER_LIMITS: Record<TierName, TierLimits> = {
    free: {
        maxBots: 1,
        coinScans: 5,
        exportCSV: false,
        intelligencePage: false,
        manualClose: false,
        apiAccess: false,
        label: 'Free Trial',
    },
    pro: {
        maxBots: 3,
        coinScans: 15,
        exportCSV: true,
        intelligencePage: true,
        manualClose: true,
        apiAccess: false,
        label: 'Pro',
    },
    ultra: {
        maxBots: 999, // effectively unlimited
        coinScans: 50,
        exportCSV: true,
        intelligencePage: true,
        manualClose: true,
        apiAccess: true,
        label: 'Ultra',
    },
};

export function getTierLimits(tier?: string | null): TierLimits {
    return TIER_LIMITS[(tier || 'free') as TierName] || TIER_LIMITS.free;
}

// God account referral code — grants Ultra forever
export const GOD_REFERRAL_CODE = 'godaccount';
