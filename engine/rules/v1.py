"""
Phase 3A - Rules engine v1.

Generates a product-level discount recommendation from variant feature vectors.
The engine is intentionally deterministic and explainable so merchants can
review why a recommendation was made before Phase 5 learning takes over.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass()
class RecommendationDraft:
    merchant_id: int
    product_id: int
    recommended_discount_pct: float
    confidence_score: float
    rationale: str
    feature_snapshot: dict[str, Any]
    model_version: str = "rules_v1"


def generate_recommendation(
    *,
    merchant_id: int,
    product_id: int,
    safe_zone_max_pct: float,
    features: list[dict[str, Any]],
) -> RecommendationDraft:
    if not features:
        raise ValueError("Cannot generate recommendation without features")

    primary = max(
        features,
        key=lambda feature: (
            float(feature["revenue_per_visitor"]),
            float(feature["conversion_rate"]),
            -float(feature["inventory_days_supply"]),
        ),
    )

    current_discount_pct = mean(float(f["current_discount_pct"]) * 100 for f in features)
    avg_conversion = mean(float(f["conversion_rate"]) for f in features)
    avg_rpv = mean(float(f["revenue_per_visitor"]) for f in features)
    avg_inventory_days = mean(float(f["inventory_days_supply"]) for f in features)
    max_inventory_days = max(float(f["inventory_days_supply"]) for f in features)
    min_inventory_days = min(float(f["inventory_days_supply"]) for f in features)
    avg_day_of_week_bias = mean(float(f["day_of_week_bias"]) for f in features)
    total_tests_run = sum(int(f["tests_run"]) for f in features)
    positive_tests = sum(1 for f in features if f["last_test_outcome"] == "positive")
    negative_tests = sum(1 for f in features if f["last_test_outcome"] == "negative")
    has_active_experiment = any(bool(f["has_active_experiment"]) for f in features)

    rule_notes: list[str] = []
    confidence = 0.62

    # Start from cold-start prior or current discount if the product already has one.
    if current_discount_pct > 0:
        target_discount_pct = current_discount_pct
        rule_notes.append(
            f"Starting from the current live discount of {current_discount_pct:.1f}%."
        )
        confidence += 0.04
    else:
        target_discount_pct = _cold_start_prior(primary, avg_inventory_days)
        rule_notes.append(
            f"Cold-start prior sets a baseline of {target_discount_pct:.1f}% for {primary['price_tier']} items."
        )

    # Rule 1: active experiment lock.
    if has_active_experiment:
        target_discount_pct = max(target_discount_pct, current_discount_pct)
        rule_notes.append(
            "An active experiment already exists for this product, so the recommendation stays conservative."
        )

    # Rule 2: overstock push.
    if max_inventory_days >= 75 and avg_conversion < 0.45:
        inventory_push = 5.0 if max_inventory_days < 120 else 8.0
        target_discount_pct += inventory_push
        confidence += 0.08
        rule_notes.append(
            f"Inventory is heavy ({max_inventory_days:.1f} days supply max) while sell-through is soft, so the engine pushes markdowns."
        )

    # Rule 3: demand protection.
    if avg_conversion >= 1.0 or avg_rpv >= 60 or min_inventory_days <= 14:
        demand_pull = 5.0 if avg_conversion >= 1.5 or min_inventory_days <= 7 else 3.0
        target_discount_pct -= demand_pull
        confidence += 0.08
        rule_notes.append(
            "Demand looks healthy or inventory is tight, so the engine protects margin by pulling the discount down."
        )

    # Rule 4: prior experiment outcomes and weekly bias.
    if positive_tests > negative_tests:
        target_discount_pct += 2.5
        confidence += 0.05
        rule_notes.append(
            "Prior experiments skew positive, so the engine leans slightly more aggressive."
        )
    elif negative_tests > positive_tests:
        target_discount_pct -= 2.5
        confidence += 0.05
        rule_notes.append(
            "Prior experiments skew negative, so the engine tempers the recommendation."
        )

    if avg_day_of_week_bias >= 1.15:
        target_discount_pct += 1.5
        rule_notes.append(
            "Recent demand is running ahead of the 14-day baseline, which supports a modest promotional push."
        )
    elif avg_day_of_week_bias <= 0.85:
        target_discount_pct -= 1.5
        rule_notes.append(
            "Recent demand is below the 14-day baseline, so the engine avoids overcommitting discount depth."
        )

    if total_tests_run == 0:
        confidence -= 0.05
    else:
        confidence += min(total_tests_run * 0.01, 0.08)

    # Active experiment hard cap applied after all rules so later rules cannot
    # push confidence back above the 0.58 ceiling.
    if has_active_experiment:
        confidence = min(confidence, 0.58)

    recommended_discount_pct = _clamp(target_discount_pct, 0.0, safe_zone_max_pct)
    confidence_score = _clamp(confidence, 0.5, 0.95)

    rationale = " ".join(rule_notes)
    snapshot = {
        "product_id": product_id,
        "merchant_id": merchant_id,
        "safe_zone_max_pct": safe_zone_max_pct,
        "primary_variant_id": int(primary["variant_id"]),
        "primary_variant_title": str(primary["product_title"]),
        "current_discount_pct": round(current_discount_pct, 2),
        "recommended_discount_pct": round(recommended_discount_pct, 2),
        "avg_conversion_rate": round(avg_conversion, 4),
        "avg_revenue_per_visitor": round(avg_rpv, 4),
        "avg_inventory_days_supply": round(avg_inventory_days, 2),
        "max_inventory_days_supply": round(max_inventory_days, 2),
        "day_of_week_bias": round(avg_day_of_week_bias, 4),
        "positive_tests": positive_tests,
        "negative_tests": negative_tests,
        "tests_run": total_tests_run,
        "has_active_experiment": has_active_experiment,
        "rules_version": "rules_v1",
    }

    return RecommendationDraft(
        merchant_id=merchant_id,
        product_id=product_id,
        recommended_discount_pct=round(recommended_discount_pct, 2),
        confidence_score=round(confidence_score, 3),
        rationale=rationale,
        feature_snapshot=snapshot,
    )


def _cold_start_prior(primary_feature: dict[str, Any], avg_inventory_days: float) -> float:
    base_by_tier = {
        "under_25": 5.0,
        "25_to_50": 7.5,
        "50_to_100": 10.0,
        "100_to_250": 12.5,
        "over_250": 10.0,
    }
    base = base_by_tier.get(str(primary_feature["price_tier"]), 10.0)
    if avg_inventory_days >= 90:
        base += 5.0
    elif avg_inventory_days <= 21:
        base -= 2.5
    return max(base, 0.0)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))
