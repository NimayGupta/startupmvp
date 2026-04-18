/**
 * Phase 6C — Stripe Billing Server Utilities
 *
 * All Stripe interaction is server-only. Never import this from client code.
 *
 * Environment variables required:
 *   STRIPE_SECRET_KEY         — sk_live_... or sk_test_...
 *   STRIPE_WEBHOOK_SECRET     — whsec_... (from Stripe dashboard)
 *   STRIPE_GROWTH_PRICE_ID    — price_... for $49/month Growth plan
 *   STRIPE_PRO_PRICE_ID       — price_... for $99/month Pro plan
 */

import Stripe from "stripe";
import { query } from "./db.server";

if (!process.env.STRIPE_SECRET_KEY) {
  console.warn("[stripe] STRIPE_SECRET_KEY not set — billing disabled");
}

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY ?? "sk_test_placeholder", {
  apiVersion: "2025-01-27.acacia",
});

export const STRIPE_WEBHOOK_SECRET = process.env.STRIPE_WEBHOOK_SECRET ?? "";

export const PRICE_IDS: Record<string, string> = {
  growth: process.env.STRIPE_GROWTH_PRICE_ID ?? "",
  pro: process.env.STRIPE_PRO_PRICE_ID ?? "",
};

export const PLAN_DISPLAY: Record<string, { name: string; price: string; features: string[] }> = {
  free: {
    name: "Free",
    price: "$0/month",
    features: ["1 product", "1 concurrent experiment", "Rules-based engine"],
  },
  growth: {
    name: "Growth",
    price: "$49/month",
    features: [
      "20 products",
      "5 concurrent experiments",
      "AI bandit engine",
      "Weekly performance reports",
    ],
  },
  pro: {
    name: "Pro",
    price: "$99/month",
    features: [
      "Unlimited products",
      "Unlimited experiments",
      "Auto-approve trusted recommendations",
      "Priority support",
    ],
  },
};

export interface SubscriptionRecord {
  id: number;
  merchant_id: number;
  stripe_customer_id: string;
  stripe_subscription_id: string | null;
  plan: string;
  status: string;
  current_period_end: string | null;
}

export interface UsageMetrics {
  products_count: number;
  active_experiments: number;
  recommendations_this_month: number;
  approval_rate_pct: number;
}

// ---------------------------------------------------------------------------
// DB helpers
// ---------------------------------------------------------------------------

export async function getSubscription(merchantId: number): Promise<SubscriptionRecord | null> {
  const rows = await query<SubscriptionRecord>(
    `SELECT id, merchant_id, stripe_customer_id, stripe_subscription_id,
            plan, status, current_period_end
     FROM subscriptions
     WHERE merchant_id = $1`,
    [merchantId],
  );
  return rows[0] ?? null;
}

export async function upsertSubscription(
  merchantId: number,
  stripeCustomerId: string,
  plan: string,
  status: string,
  stripeSubscriptionId?: string | null,
  currentPeriodEnd?: Date | null,
): Promise<void> {
  await query(
    `INSERT INTO subscriptions
       (merchant_id, stripe_customer_id, stripe_subscription_id, plan, status,
        current_period_start, current_period_end)
     VALUES ($1, $2, $3, $4, $5, NOW(), $6)
     ON CONFLICT (merchant_id) DO UPDATE
       SET stripe_customer_id     = EXCLUDED.stripe_customer_id,
           stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id, subscriptions.stripe_subscription_id),
           plan                   = EXCLUDED.plan,
           status                 = EXCLUDED.status,
           current_period_end     = COALESCE(EXCLUDED.current_period_end, subscriptions.current_period_end),
           updated_at             = NOW()`,
    [
      merchantId,
      stripeCustomerId,
      stripeSubscriptionId ?? null,
      plan,
      status,
      currentPeriodEnd ?? null,
    ],
  );
}

export async function getUsageMetrics(merchantId: number): Promise<UsageMetrics> {
  const rows = await query<{
    products_count: string;
    active_experiments: string;
    recommendations_this_month: string;
    approved: string;
    total_reviewed: string;
  }>(
    `SELECT
       (SELECT COUNT(*) FROM products WHERE merchant_id = $1 AND status = 'active')::text
         AS products_count,
       (SELECT COUNT(*) FROM experiments WHERE merchant_id = $1 AND status = 'active')::text
         AS active_experiments,
       (SELECT COUNT(*) FROM recommendations
        WHERE merchant_id = $1 AND created_at >= date_trunc('month', NOW()))::text
         AS recommendations_this_month,
       (SELECT COUNT(*) FROM recommendations
        WHERE merchant_id = $1 AND status IN ('approved','edited_and_approved')
          AND created_at >= date_trunc('month', NOW()))::text AS approved,
       (SELECT COUNT(*) FROM recommendations
        WHERE merchant_id = $1 AND status != 'pending'
          AND created_at >= date_trunc('month', NOW()))::text AS total_reviewed`,
    [merchantId],
  );
  const r = rows[0];
  const approved = parseInt(r?.approved ?? "0", 10);
  const totalReviewed = parseInt(r?.total_reviewed ?? "0", 10);
  return {
    products_count: parseInt(r?.products_count ?? "0", 10),
    active_experiments: parseInt(r?.active_experiments ?? "0", 10),
    recommendations_this_month: parseInt(r?.recommendations_this_month ?? "0", 10),
    approval_rate_pct: totalReviewed > 0 ? Math.round((approved / totalReviewed) * 100) : 0,
  };
}

// ---------------------------------------------------------------------------
// Stripe session helpers
// ---------------------------------------------------------------------------

export async function createCheckoutSession(
  merchantId: number,
  shopDomain: string,
  plan: "growth" | "pro",
  successUrl: string,
  cancelUrl: string,
): Promise<string> {
  const priceId = PRICE_IDS[plan];
  if (!priceId) throw new Error(`No price ID configured for plan: ${plan}`);

  // Reuse or create Stripe customer
  let sub = await getSubscription(merchantId);
  let customerId = sub?.stripe_customer_id;

  if (!customerId) {
    const customer = await stripe.customers.create({
      metadata: { merchant_id: String(merchantId), shop_domain: shopDomain },
    });
    customerId = customer.id;
    await upsertSubscription(merchantId, customerId, "free", "active");
  }

  const session = await stripe.checkout.sessions.create({
    customer: customerId,
    mode: "subscription",
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: successUrl,
    cancel_url: cancelUrl,
    metadata: { merchant_id: String(merchantId), plan },
  });

  return session.url ?? "";
}

export async function createPortalSession(
  merchantId: number,
  returnUrl: string,
): Promise<string> {
  const sub = await getSubscription(merchantId);
  if (!sub?.stripe_customer_id) throw new Error("No Stripe customer found");

  const session = await stripe.billingPortal.sessions.create({
    customer: sub.stripe_customer_id,
    return_url: returnUrl,
  });
  return session.url;
}
