"""
Phase 2A — Features API endpoint

GET /features/{merchant_id}
  Returns all variant feature vectors for a merchant.
  Serves from Redis cache (6h TTL). Pass ?refresh=true to force recompute.

Protected by RequireInternalAuth (Bearer INTERNAL_API_KEY).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from engine.api.deps import DbSession, RedisClient, RequireInternalAuth
from engine.features.compute import compute_merchant_features
from engine.features.store import read_merchant_features, write_merchant_features

router = APIRouter()


@router.get(
    "/features/{merchant_id}",
    tags=["features"],
    dependencies=[RequireInternalAuth],
)
async def get_merchant_features(
    merchant_id: int,
    db: DbSession,
    redis: RedisClient,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    Returns all variant feature vectors for a merchant.

    - Serves from Redis if cached and refresh=false (default).
    - Forces recomputation and cache write when refresh=true.
    - Returns an empty features list (not 404) for merchants with no synced products.
    """
    if not refresh:
        cached = await read_merchant_features(redis, merchant_id)
        if cached is not None:
            return {
                "merchant_id": merchant_id,
                "source": "cache",
                "features": cached,
            }

    features = await compute_merchant_features(db, merchant_id)
    await write_merchant_features(redis, merchant_id, features)

    return {
        "merchant_id": merchant_id,
        "source": "computed",
        "features": features,
    }
