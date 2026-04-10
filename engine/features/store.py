"""
Phase 2A — Redis Feature Vector Store

Reads and writes variant feature vectors to Redis.

Key pattern:
  features:{merchant_id}:{variant_id}  →  JSON blob (TTL 6h)
  features:{merchant_id}:_index        →  JSON list of variant_ids (TTL 6h)

The _index key lets bulk reads do a single GET + MGET instead of a Redis SCAN.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

_PREFIX = "features"
_TTL = 6 * 3600  # 6 hours


async def write_merchant_features(
    redis: aioredis.Redis,  # type: ignore[type-arg]
    merchant_id: int,
    features: list[dict[str, Any]],
) -> None:
    """
    Writes all variant feature vectors for a merchant to Redis in a single
    pipeline round-trip. Also writes an index key for bulk retrieval.
    """
    if not features:
        return

    pipe = redis.pipeline()
    variant_ids: list[int] = []

    for fv in features:
        key = f"{_PREFIX}:{merchant_id}:{fv['variant_id']}"
        pipe.set(key, json.dumps(fv), ex=_TTL)
        variant_ids.append(fv["variant_id"])

    index_key = f"{_PREFIX}:{merchant_id}:_index"
    pipe.set(index_key, json.dumps(variant_ids), ex=_TTL)

    await pipe.execute()


async def read_merchant_features(
    redis: aioredis.Redis,  # type: ignore[type-arg]
    merchant_id: int,
) -> list[dict[str, Any]] | None:
    """
    Returns all feature vectors for a merchant from Redis.
    Returns None on cache miss (index key absent or expired).
    Returns [] if the merchant has no active variants.
    """
    index_key = f"{_PREFIX}:{merchant_id}:_index"
    index_raw = await redis.get(index_key)

    if index_raw is None:
        return None  # cache miss

    variant_ids: list[int] = json.loads(index_raw)
    if not variant_ids:
        return []

    keys = [f"{_PREFIX}:{merchant_id}:{vid}" for vid in variant_ids]
    values = await redis.mget(*keys)

    return [json.loads(v) for v in values if v is not None]


async def read_variant_features(
    redis: aioredis.Redis,  # type: ignore[type-arg]
    merchant_id: int,
    variant_id: int,
) -> dict[str, Any] | None:
    """
    Returns the feature vector for a single variant, or None on cache miss.
    """
    key = f"{_PREFIX}:{merchant_id}:{variant_id}"
    raw = await redis.get(key)
    return json.loads(raw) if raw is not None else None
