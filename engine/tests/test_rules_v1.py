from engine.rules.v1 import generate_recommendation


def _feature(**overrides):
    base = {
        "variant_id": 1,
        "product_id": 10,
        "product_title": "Test Product",
        "conversion_rate": 0.2,
        "revenue_per_visitor": 8.0,
        "avg_order_value": 40.0,
        "inventory_days_supply": 120.0,
        "current_discount_pct": 0.0,
        "price_tier": "50_to_100",
        "day_of_week_bias": 1.0,
        "tests_run": 0,
        "last_test_outcome": "none",
        "has_active_experiment": False,
    }
    base.update(overrides)
    return base


def test_overstock_rule_pushes_discount_up():
    draft = generate_recommendation(
        merchant_id=1,
        product_id=10,
        safe_zone_max_pct=25.0,
        features=[_feature()],
    )

    assert draft.recommended_discount_pct >= 15.0
    assert "Inventory is heavy" in draft.rationale


def test_demand_protection_pulls_discount_down():
    draft = generate_recommendation(
        merchant_id=1,
        product_id=10,
        safe_zone_max_pct=20.0,
        features=[
            _feature(
                conversion_rate=1.7,
                revenue_per_visitor=75.0,
                inventory_days_supply=10.0,
                current_discount_pct=0.15,
                tests_run=4,
            )
        ],
    )

    assert draft.recommended_discount_pct <= 12.0
    assert "protects margin" in draft.rationale


def test_active_experiment_caps_confidence():
    draft = generate_recommendation(
        merchant_id=1,
        product_id=10,
        safe_zone_max_pct=20.0,
        features=[_feature(has_active_experiment=True, current_discount_pct=0.1)],
    )

    assert draft.confidence_score <= 0.58
    assert "active experiment" in draft.rationale.lower()
