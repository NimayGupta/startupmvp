/**
 * Phase 4B — Active Experiment Lookup API
 *
 * Called by the Checkout UI Extension to determine if any product in the
 * cart has an active A/B experiment.
 *
 * GET /api/active-experiment?product_ids=123,456
 *
 * Returns:
 *   { experiment: { id, treatment_discount_pct } | null }
 *
 * Authentication: Shopify session token (Bearer) passed by the checkout
 * extension via useSessionToken().get().  For MVP the token is verified
 * structurally (signed JWT); full verification requires the Shopify API key.
 */

import type { LoaderFunctionArgs } from "@remix-run/node";
import { json } from "@remix-run/node";
import { query } from "../lib/db.server";

interface ActiveExperimentRow {
  id: number;
  treatment_discount_pct: string;
}

export async function loader({ request }: LoaderFunctionArgs) {
  const url = new URL(request.url);
  const productIdsParam = url.searchParams.get("product_ids") ?? "";
  const productIds = productIdsParam
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  if (productIds.length === 0) {
    return json({ experiment: null });
  }

  // Look up active experiments for these Shopify product IDs
  const rows = await query<ActiveExperimentRow>(
    `SELECT e.id, e.treatment_discount_pct::text
     FROM experiments e
     JOIN products p ON p.id = e.product_id
     WHERE p.shopify_product_id = ANY($1)
       AND e.status = 'active'
     ORDER BY e.started_at DESC
     LIMIT 1`,
    [productIds],
  );

  if (rows.length === 0) {
    return json({ experiment: null });
  }

  return json({
    experiment: {
      id: rows[0].id,
      treatment_discount_pct: parseFloat(rows[0].treatment_discount_pct),
    },
  });
}
