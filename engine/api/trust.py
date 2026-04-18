"""
Phase 5E — Trust Score API

GET /trust/{merchant_id}/{product_id}
  Returns the current trust score for a product along with eligibility metadata.

Called by the Remix app when loading the product detail page.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from engine.api.deps import DbSession, RequireInternalAuth
from engine.trust.scorer import get_trust_score

router = APIRouter(prefix="/trust")


@router.get("/{merchant_id}/{product_id}", dependencies=[RequireInternalAuth])
async def get_product_trust(
    merchant_id: int,
    product_id: int,
    db: DbSession,
) -> dict[str, Any]:
    """
    Return trust score and auto-approve eligibility for a product.

    Response fields
    ---------------
    trust_score          : float  0.0–1.0
    tests_completed      : int    total completed experiments
    tests_positive       : int    experiments where treatment RPV > control × 1.02
    auto_approve_eligible: bool   trust_score >= 0.70
    tests_needed         : int    additional positive tests to reach eligibility (0 if eligible)
    """
    return await get_trust_score(db, merchant_id, product_id)
