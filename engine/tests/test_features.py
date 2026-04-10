"""Unit tests for engine/features/compute.py"""

import pytest
from engine.features.compute import _build_feature_vector, _price_tier


# ---------------------------------------------------------------------------
# _price_tier
# ---------------------------------------------------------------------------


def test_price_tier_under_25():
    assert _price_tier(9.99) == "under_25"


def test_price_tier_25_to_50():
    assert _price_tier(25.0) == "25_to_50"
    assert _price_tier(49.99) == "25_to_50"


def test_price_tier_50_to_100():
    assert _price_tier(50.0) == "50_to_100"
    assert _price_tier(99.99) == "50_to_100"


def test_price_tier_100_to_250():
    assert _price_tier(100.0) == "100_to_250"
    assert _price_tier(249.99) == "100_to_250"


def test_price_tier_over_250():
    assert _price_tier(250.0) == "over_250"
    assert _price_tier(999.0) == "over_250"


# ---------------------------------------------------------------------------
# _build_feature_vector — helper to produce fake mapping rows
# ---------------------------------------------------------------------------


def _make_row(**overrides):
    defaults = {
        "variant_id": 1,
        "shopify_variant_id": "gid://shopify/ProductVariant/111",
        "product_id": 10,
        "shopify_product_id": "gid://shopify/Product/999",
        "product_title": "Test Product",
        "price": "49.99",
        "compare_at_price": None,
        "inventory_quantity": 100,
        "order_count": 28,
        "order_count_7d": 14,
        "units_sold": 30,
        "total_revenue": "1399.72",
        "avg_order_value": "49.99",
        "tests_run": 3,
        "last_test_outcome": "positive",
        "has_active_experiment": False,
    }
    defaults.update(overrides)
    return defaults


def test_basic_feature_vector():
    row = _make_row()
    fv = _build_feature_vector(row)

    assert fv["variant_id"] == 1
    assert fv["product_id"] == 10
    assert fv["price_tier"] == "25_to_50"
    assert fv["current_discount_pct"] == 0.0  # no compare_at_price
    assert fv["conversion_rate"] == pytest.approx(28 / 14.0, rel=1e-4)
    assert fv["revenue_per_visitor"] == pytest.approx(float("1399.72") / 14.0, rel=1e-4)
    assert fv["inventory_days_supply"] == pytest.approx(
        min(100 / (30 / 14.0), 365), rel=1e-2
    )
    assert fv["tests_run"] == 3
    assert fv["last_test_outcome"] == "positive"
    assert fv["has_active_experiment"] is False


def test_discount_pct_computed_when_compare_at_price_set():
    row = _make_row(price="40.00", compare_at_price="50.00")
    fv = _build_feature_vector(row)
    assert fv["current_discount_pct"] == pytest.approx(0.2, rel=1e-4)


def test_no_discount_when_compare_at_lower_than_price():
    row = _make_row(price="50.00", compare_at_price="40.00")
    fv = _build_feature_vector(row)
    assert fv["current_discount_pct"] == 0.0


def test_inventory_days_capped_at_365_for_zero_sales():
    row = _make_row(units_sold=0, inventory_quantity=9999)
    fv = _build_feature_vector(row)
    assert fv["inventory_days_supply"] == 365.0


def test_zero_order_count_produces_zero_conversion_rate():
    row = _make_row(order_count=0, order_count_7d=0, units_sold=0, total_revenue="0")
    fv = _build_feature_vector(row)
    assert fv["conversion_rate"] == 0.0
    assert fv["revenue_per_visitor"] == 0.0


def test_day_of_week_bias_above_one_when_recent_spike():
    # 7d rate (20/7) > 14d rate (28/14)
    row = _make_row(order_count=28, order_count_7d=20)
    fv = _build_feature_vector(row)
    assert fv["day_of_week_bias"] > 1.0


def test_feature_vector_has_all_required_keys():
    required_keys = {
        "variant_id", "shopify_variant_id", "product_id", "shopify_product_id",
        "product_title", "conversion_rate", "revenue_per_visitor",
        "avg_order_value", "inventory_days_supply", "current_discount_pct",
        "price_tier", "day_of_week_bias", "tests_run", "last_test_outcome",
        "has_active_experiment", "computed_at",
    }
    fv = _build_feature_vector(_make_row())
    assert required_keys.issubset(set(fv.keys()))
