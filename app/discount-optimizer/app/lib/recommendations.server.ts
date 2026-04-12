const ENGINE_URL = process.env.ENGINE_URL ?? "http://localhost:8000";
const INTERNAL_API_KEY = process.env.INTERNAL_API_KEY ?? "";

export interface RecommendationRecord {
  id: number;
  merchant_id: number;
  product_id: number;
  recommended_discount_pct: number;
  rationale: string;
  llm_explanation: string;
  confidence_score: number;
  model_version: string;
  feature_snapshot: Record<string, unknown>;
  status: "pending" | "approved" | "rejected" | "edited_and_approved";
  merchant_edit_pct: number | null;
  created_at: string;
  reviewed_at: string | null;
}

async function engineFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${ENGINE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${INTERNAL_API_KEY}`,
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    signal: AbortSignal.timeout(10_000),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`[engine] ${res.status} ${path}: ${body}`);
  }

  return (await res.json()) as T;
}

export async function fetchLatestRecommendation(
  merchantId: number,
  productId: number,
): Promise<RecommendationRecord | null> {
  try {
    return await engineFetch<RecommendationRecord>(
      `/recommendations/${merchantId}/products/${productId}`,
      { method: "GET" },
    );
  } catch {
    return null;
  }
}

export async function generateRecommendation(
  merchantId: number,
  productId: number,
): Promise<RecommendationRecord> {
  return engineFetch<RecommendationRecord>("/recommendations/generate", {
    method: "POST",
    body: JSON.stringify({
      merchant_id: merchantId,
      product_id: productId,
    }),
  });
}

export async function approveRecommendation(
  recommendationId: number,
  shopifyDiscountId: string,
  appliedDiscountPct?: number,
): Promise<RecommendationRecord> {
  return engineFetch<RecommendationRecord>(
    `/recommendations/${recommendationId}/approve`,
    {
      method: "POST",
      body: JSON.stringify({
        shopify_discount_id: shopifyDiscountId,
        applied_discount_pct: appliedDiscountPct,
      }),
    },
  );
}

export async function rejectRecommendation(
  recommendationId: number,
  reason?: string,
): Promise<RecommendationRecord> {
  return engineFetch<RecommendationRecord>(
    `/recommendations/${recommendationId}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );
}

export async function editApproveRecommendation(
  recommendationId: number,
  merchantEditPct: number,
  shopifyDiscountId: string,
): Promise<RecommendationRecord> {
  return engineFetch<RecommendationRecord>(
    `/recommendations/${recommendationId}/edit-approve`,
    {
      method: "POST",
      body: JSON.stringify({
        merchant_edit_pct: merchantEditPct,
        shopify_discount_id: shopifyDiscountId,
      }),
    },
  );
}
