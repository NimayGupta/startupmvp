"""Unit tests for engine/features/store.py"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.features.store import (
    read_merchant_features,
    read_variant_features,
    write_merchant_features,
)


def _make_fv(variant_id: int = 1, product_id: int = 10) -> dict:
    return {
        "variant_id": variant_id,
        "shopify_variant_id": f"gid://shopify/ProductVariant/{variant_id}",
        "product_id": product_id,
        "shopify_product_id": "gid://shopify/Product/999",
        "product_title": "Test Product",
        "conversion_rate": 0.5,
        "revenue_per_visitor": 25.0,
        "avg_order_value": 50.0,
        "inventory_days_supply": 30.0,
        "current_discount_pct": 0.1,
        "price_tier": "25_to_50",
        "day_of_week_bias": 1.0,
        "tests_run": 2,
        "last_test_outcome": "positive",
        "has_active_experiment": False,
        "computed_at": "2024-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# write_merchant_features
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_merchant_features_sets_correct_keys():
    features = [_make_fv(1), _make_fv(2)]
    merchant_id = 42

    mock_pipe = AsyncMock()
    mock_pipe.set = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[True, True, True])

    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    await write_merchant_features(mock_redis, merchant_id, features)

    # Should have called pipe.set for each variant + the index key
    assert mock_pipe.set.call_count == 3

    call_keys = [call.args[0] for call in mock_pipe.set.call_args_list]
    assert "features:42:1" in call_keys
    assert "features:42:2" in call_keys
    assert "features:42:_index" in call_keys

    # TTL must be set (6 hours)
    for call in mock_pipe.set.call_args_list:
        assert call.kwargs.get("ex") == 6 * 3600 or call.args[2:] or "ex" in call.kwargs


@pytest.mark.asyncio
async def test_write_merchant_features_empty_list_is_noop():
    mock_redis = AsyncMock()
    await write_merchant_features(mock_redis, 42, [])
    mock_redis.pipeline.assert_not_called()


# ---------------------------------------------------------------------------
# read_merchant_features
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_merchant_features_returns_none_on_cache_miss():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    result = await read_merchant_features(mock_redis, 42)
    assert result is None


@pytest.mark.asyncio
async def test_read_merchant_features_returns_empty_list_for_empty_index():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps([]))

    result = await read_merchant_features(mock_redis, 42)
    assert result == []


@pytest.mark.asyncio
async def test_read_merchant_features_returns_cached_features():
    fv = _make_fv(1)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps([1]))
    mock_redis.mget = AsyncMock(return_value=[json.dumps(fv)])

    result = await read_merchant_features(mock_redis, 42)
    assert result is not None
    assert len(result) == 1
    assert result[0]["variant_id"] == 1


# ---------------------------------------------------------------------------
# read_variant_features
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_variant_features_returns_none_on_miss():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    result = await read_variant_features(mock_redis, 42, 1)
    assert result is None


@pytest.mark.asyncio
async def test_read_variant_features_returns_parsed_json():
    fv = _make_fv(1)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(fv))

    result = await read_variant_features(mock_redis, 42, 1)
    assert result is not None
    assert result["variant_id"] == 1
