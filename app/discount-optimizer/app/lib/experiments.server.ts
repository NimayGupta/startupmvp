/**
 * Phase 4 — Experiment Engine Client
 *
 * Wrapper functions that call the FastAPI engine's /experiments endpoints.
 * All calls use Bearer INTERNAL_API_KEY auth and return null on failure
 * (graceful degradation — UI shows appropriate empty states).
 */

const ENGINE_URL = process.env.ENGINE_URL ?? "http://localhost:8000";
const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY ?? "";

const _headers = () => ({
  "Content-Type": "application/json",
  Authorization: `Bearer ${INTERNAL_API_KEY}`,
});

export interface ExperimentRecord {
  id: number;
  merchant_id: number;
  product_id: number;
  recommendation_id: number | null;
  status: string;
  control_discount_pct: number;
  treatment_discount_pct: number;
  shopify_discount_id: string;
  started_at: string | null;
  concluded_at: string | null;
  conclusion_type: string | null;
  latest_stats: ExperimentStats | null;
  created_at: string;
}

export interface ExperimentStats {
  experiment_id: number;
  control_n: number;
  treatment_n: number;
  control_conversions: number;
  treatment_conversions: number;
  control_rpv: number;
  treatment_rpv: number;
  prob_treatment_better: number;
  prob_kill_switch: number;
  significance_reached: boolean;
  kill_switch_triggered: boolean;
  days_running: number;
  last_computed_at?: string;
}

/**
 * Create and immediately activate a new A/B experiment.
 * The Shopify discount must already exist before calling this.
 */
export async function createExperiment(params: {
  merchantId: number;
  productId: number;
  recommendationId: number;
  controlDiscountPct: number;
  treatmentDiscountPct: number;
  shopifyDiscountId: string;
}): Promise<ExperimentRecord | null> {
  try {
    const resp = await fetch(`${ENGINE_URL}/experiments`, {
      method: "POST",
      headers: _headers(),
      signal: AbortSignal.timeout(10_000),
      body: JSON.stringify({
        merchant_id: params.merchantId,
        product_id: params.productId,
        recommendation_id: params.recommendationId,
        control_discount_pct: params.controlDiscountPct,
        treatment_discount_pct: params.treatmentDiscountPct,
        shopify_discount_id: params.shopifyDiscountId,
      }),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as ExperimentRecord;
  } catch {
    return null;
  }
}

/**
 * Fetch a single experiment by ID.
 */
export async function getExperiment(
  experimentId: number,
): Promise<ExperimentRecord | null> {
  try {
    const resp = await fetch(`${ENGINE_URL}/experiments/${experimentId}`, {
      headers: _headers(),
      signal: AbortSignal.timeout(10_000),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as ExperimentRecord;
  } catch {
    return null;
  }
}

/**
 * Kill an active experiment (merchant override).
 * Returns the updated experiment record or null on error.
 */
export async function killExperiment(
  experimentId: number,
  merchantId: number,
): Promise<ExperimentRecord | null> {
  try {
    const resp = await fetch(`${ENGINE_URL}/experiments/${experimentId}/kill`, {
      method: "POST",
      headers: _headers(),
      signal: AbortSignal.timeout(10_000),
      body: JSON.stringify({ merchant_id: merchantId }),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as ExperimentRecord;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Phase 5E — Trust score
// ---------------------------------------------------------------------------

export interface TrustScore {
  trust_score: number;
  tests_completed: number;
  tests_positive: number;
  auto_approve_eligible: boolean;
  /** Additional positive tests needed to reach auto-approve threshold */
  tests_needed: number;
}

/**
 * Fetch the trust score for a product.
 * Returns a zero-score record on error (graceful degradation).
 */
export async function getTrustScore(
  merchantId: number,
  productId: number,
): Promise<TrustScore> {
  const fallback: TrustScore = {
    trust_score: 0,
    tests_completed: 0,
    tests_positive: 0,
    auto_approve_eligible: false,
    tests_needed: 3,
  };
  try {
    const resp = await fetch(
      `${ENGINE_URL}/trust/${merchantId}/${productId}`,
      { headers: _headers(), signal: AbortSignal.timeout(5_000) },
    );
    if (!resp.ok) return fallback;
    return (await resp.json()) as TrustScore;
  } catch {
    return fallback;
  }
}
