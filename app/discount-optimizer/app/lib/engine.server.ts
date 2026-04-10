/**
 * FastAPI engine client for the Remix app.
 *
 * All calls have a 10-second timeout and return null on failure so the UI
 * degrades gracefully (feature columns show "—") rather than crashing.
 */

const ENGINE_URL =
  process.env.ENGINE_URL ?? "http://localhost:8000";
const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY ?? "";

export interface FeatureVector {
  variant_id: number;
  shopify_variant_id: string;
  product_id: number;
  shopify_product_id: string;
  product_title: string;
  conversion_rate: number;
  revenue_per_visitor: number;
  avg_order_value: number;
  inventory_days_supply: number;
  current_discount_pct: number;
  price_tier: string;
  day_of_week_bias: number;
  tests_run: number;
  last_test_outcome: "positive" | "negative" | "neutral" | "none";
  has_active_experiment: boolean;
  computed_at: string;
}

export interface EngineFeatureResponse {
  merchant_id: number;
  source: "cache" | "computed";
  features: FeatureVector[];
}

/**
 * Fetch all variant feature vectors for a merchant from the engine.
 * Returns null if the engine is unreachable or returns an error.
 */
export async function fetchMerchantFeatures(
  merchantId: number,
): Promise<EngineFeatureResponse | null> {
  try {
    const res = await fetch(`${ENGINE_URL}/features/${merchantId}`, {
      headers: {
        Authorization: `Bearer ${INTERNAL_API_KEY}`,
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(10_000),
    });

    if (!res.ok) {
      console.error(
        `[engine] GET /features/${merchantId} returned ${res.status}`,
      );
      return null;
    }

    return (await res.json()) as EngineFeatureResponse;
  } catch (err) {
    console.error(`[engine] fetchMerchantFeatures failed:`, err);
    return null;
  }
}

/**
 * Build a map from product_id → the "best" FeatureVector for that product
 * (variant with highest conversion_rate, to represent the product row).
 */
export function buildProductFeatureMap(
  features: FeatureVector[],
): Record<number, FeatureVector> {
  const map: Record<number, FeatureVector> = {};
  for (const fv of features) {
    const existing = map[fv.product_id];
    if (!existing || fv.conversion_rate > existing.conversion_rate) {
      map[fv.product_id] = fv;
    }
  }
  return map;
}

/**
 * Build a map from variant_id → FeatureVector.
 */
export function buildVariantFeatureMap(
  features: FeatureVector[],
): Record<number, FeatureVector> {
  return Object.fromEntries(features.map((fv) => [fv.variant_id, fv]));
}
