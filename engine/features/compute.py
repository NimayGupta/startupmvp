"""
Phase 2A — Feature Vector Computation

Computes a 9-dimension feature vector for each active product variant
over a 14-day rolling window. This module is the single source of truth
for all features used by the decision engine.

Approximation note: At MVP stage, no session data is available from Shopify.
Conversion rate and revenue-per-visitor are approximated as per-day rates
(orders or revenue / 14 days) rather than true visitor-based rates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Feature SQL
# ---------------------------------------------------------------------------

_FEATURE_SQL = text(
    """
    WITH window_orders AS (
        SELECT
            oli.shopify_variant_id,
            COUNT(*)                                                       AS order_count,
            SUM(oli.quantity)                                              AS units_sold,
            SUM(oli.price * oli.quantity)                                  AS total_revenue,
            AVG(oli.price * oli.quantity)                                  AS avg_order_value,
            COUNT(*) FILTER (
                WHERE oli.created_at >= NOW() - INTERVAL '7 days'
            )                                                              AS order_count_7d
        FROM order_line_items oli
        WHERE oli.merchant_id = :merchant_id
          AND oli.created_at  >= NOW() - INTERVAL '14 days'
        GROUP BY oli.shopify_variant_id
    ),
    experiment_history AS (
        SELECT
            e.product_id,
            COUNT(*)                                                       AS tests_run,
            (ARRAY_AGG(
                CASE
                    WHEN (e.latest_stats->>'prob_treatment_better')::float >= 0.95 THEN 'positive'
                    WHEN (e.latest_stats->>'prob_treatment_better')::float <= 0.05 THEN 'negative'
                    ELSE 'neutral'
                END
                ORDER BY e.concluded_at DESC NULLS LAST
            ))[1]                                                          AS last_test_outcome
        FROM experiments e
        WHERE e.merchant_id = :merchant_id
          AND e.status      = 'concluded'
        GROUP BY e.product_id
    )
    SELECT
        pv.id                                                              AS variant_id,
        pv.shopify_variant_id,
        pv.price,
        pv.compare_at_price,
        pv.inventory_quantity,
        p.id                                                               AS product_id,
        p.title                                                            AS product_title,
        p.shopify_product_id,
        COALESCE(wo.order_count,    0)                                     AS order_count,
        COALESCE(wo.order_count_7d, 0)                                     AS order_count_7d,
        COALESCE(wo.units_sold,     0)                                     AS units_sold,
        COALESCE(wo.total_revenue,  0)                                     AS total_revenue,
        COALESCE(wo.avg_order_value, 0)                                    AS avg_order_value,
        COALESCE(eh.tests_run,      0)                                     AS tests_run,
        COALESCE(eh.last_test_outcome, 'none')                             AS last_test_outcome,
        EXISTS(
            SELECT 1 FROM experiments e2
            WHERE e2.product_id  = p.id
              AND e2.merchant_id = :merchant_id
              AND e2.status      = 'active'
        )                                                                  AS has_active_experiment
    FROM product_variants pv
    JOIN products p ON p.id = pv.product_id
    LEFT JOIN window_orders wo       ON wo.shopify_variant_id = pv.shopify_variant_id
    LEFT JOIN experiment_history eh  ON eh.product_id         = p.id
    WHERE p.merchant_id = :merchant_id
      AND p.status      = 'active'
    ORDER BY p.title, pv.price
    """
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compute_merchant_features(
    db: AsyncSession,
    merchant_id: int,
) -> list[dict[str, Any]]:
    """
    Runs the feature SQL for a single merchant and returns a list of
    FeatureVector dicts, one per active variant. Pure computation — no
    Redis writes. Call engine/features/store.py to persist results.
    """
    result = await db.execute(_FEATURE_SQL, {"merchant_id": merchant_id})
    return [_build_feature_vector(row) for row in result.mappings()]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _price_tier(price: float) -> str:
    if price < 25:
        return "under_25"
    if price < 50:
        return "25_to_50"
    if price < 100:
        return "50_to_100"
    if price < 250:
        return "100_to_250"
    return "over_250"


def _build_feature_vector(row: Mapping[str, Any]) -> dict[str, Any]:
    price = float(row["price"] or 0)
    compare_at = float(row["compare_at_price"] or 0)
    inventory = int(row["inventory_quantity"] or 0)
    order_count = int(row["order_count"] or 0)
    order_count_7d = int(row["order_count_7d"] or 0)
    units_sold = float(row["units_sold"] or 0)
    total_revenue = float(row["total_revenue"] or 0)
    avg_order_value = float(row["avg_order_value"] or 0)

    # current discount relative to compare_at_price
    current_discount_pct = (
        round((compare_at - price) / compare_at, 4)
        if compare_at > price
        else 0.0
    )

    # inventory days supply (capped at 365 to avoid infinity)
    daily_units = units_sold / 14.0
    inventory_days_supply = round(
        min(inventory / max(daily_units, 0.01), 365.0), 1
    )

    # day-of-week bias: ratio of 7d daily rate to 14d daily rate
    daily_rate_14d = order_count / 14.0
    daily_rate_7d = order_count_7d / 7.0
    day_of_week_bias = round(
        daily_rate_7d / max(daily_rate_14d, 0.001), 4
    )

    return {
        "variant_id": int(row["variant_id"]),
        "shopify_variant_id": str(row["shopify_variant_id"]),
        "product_id": int(row["product_id"]),
        "shopify_product_id": str(row["shopify_product_id"]),
        "product_title": str(row["product_title"]),
        # ---- computed metrics ----
        "conversion_rate": round(order_count / 14.0, 6),
        "revenue_per_visitor": round(total_revenue / 14.0, 4),
        "avg_order_value": round(avg_order_value, 4),
        "inventory_days_supply": inventory_days_supply,
        "current_discount_pct": current_discount_pct,
        "price_tier": _price_tier(price),
        "day_of_week_bias": day_of_week_bias,
        "tests_run": int(row["tests_run"] or 0),
        "last_test_outcome": str(row["last_test_outcome"]),
        "has_active_experiment": bool(row["has_active_experiment"]),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
