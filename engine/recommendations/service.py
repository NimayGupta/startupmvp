from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from engine.bandit.thompson import compute_context_bucket, generate_bandit_recommendation
from engine.engine_selector import maybe_promote_to_bandit, select_engine
from engine.features.compute import compute_merchant_features
from engine.recommendations.explain import ExplanationContext, get_explainer
from engine.rules.v1 import generate_recommendation
from engine.trust.scorer import _AUTO_APPROVE_THRESHOLD, get_trust_score

logger = logging.getLogger(__name__)


async def get_latest_recommendation(
    db: AsyncSession,
    merchant_id: int,
    product_id: int,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT
              r.id,
              r.merchant_id,
              r.product_id,
              p.title AS product_title,
              r.recommended_discount_pct,
              r.rationale,
              r.llm_explanation,
              r.confidence_score,
              r.model_version,
              r.feature_snapshot,
              r.status,
              r.merchant_edit_pct,
              r.created_at,
              r.reviewed_at
            FROM recommendations r
            JOIN products p ON p.id = r.product_id
            WHERE r.merchant_id = :merchant_id
              AND r.product_id = :product_id
            ORDER BY r.created_at DESC
            LIMIT 1
            """
        ),
        {"merchant_id": merchant_id, "product_id": product_id},
    )
    row = result.mappings().first()
    return _serialize_recommendation(row) if row else None


async def generate_or_get_recommendation(
    db: AsyncSession,
    merchant_id: int,
    product_id: int,
) -> dict[str, Any]:
    existing = await get_latest_recommendation(db, merchant_id, product_id)
    if existing and existing["status"] == "pending":
        return existing

    merchant = await _get_merchant(db, merchant_id)
    product = await _get_product(db, merchant_id, product_id)
    features = [
        feature
        for feature in await compute_merchant_features(db, merchant_id)
        if int(feature["product_id"]) == product_id
    ]
    if not features:
        raise ValueError("No features available for this product yet")

    # ------------------------------------------------------------------
    # Engine selection: rules_v1 or bandit_v1 (Phase 5B)
    # ------------------------------------------------------------------
    safe_zone = float(merchant["safe_zone_max_pct"])
    context_bucket = compute_context_bucket(features)
    engine_version = await select_engine(db, merchant_id, context_bucket)

    if engine_version == "bandit_v1":
        draft = await generate_bandit_recommendation(
            db=db,
            merchant_id=merchant_id,
            product_id=product_id,
            safe_zone_max_pct=safe_zone,
            features=features,
        )
        # Embed context_bucket in snapshot so retraining can find it later
        draft.feature_snapshot["context_bucket"] = context_bucket
    else:
        draft = generate_recommendation(
            merchant_id=merchant_id,
            product_id=product_id,
            safe_zone_max_pct=safe_zone,
            features=features,
        )
        # Embed context_bucket so retrain still works if merchant later promotes
        draft.feature_snapshot["context_bucket"] = context_bucket

    logger.info(
        "Recommendation generated: merchant=%d product=%d engine=%s discount=%.1f%%",
        merchant_id, product_id, engine_version, draft.recommended_discount_pct,
    )

    # ------------------------------------------------------------------
    # Auto-approve check (Phase 5E)
    # ------------------------------------------------------------------
    auto_approve_eligible = await _check_auto_approve(
        db, merchant_id, product_id,
        recommended_pct=draft.recommended_discount_pct,
        merchant=merchant,
    )
    draft.feature_snapshot["auto_approve_eligible"] = auto_approve_eligible

    # ------------------------------------------------------------------
    # Persist recommendation
    # ------------------------------------------------------------------
    explainer = get_explainer()
    llm_explanation = explainer.generate(
        ExplanationContext(
            product_title=str(product["title"]),
            recommended_discount_pct=draft.recommended_discount_pct,
            confidence_score=draft.confidence_score,
            rationale=draft.rationale,
        )
    )

    inserted = await db.execute(
        text(
            """
            INSERT INTO recommendations (
              merchant_id, product_id, recommended_discount_pct,
              rationale, llm_explanation, confidence_score,
              model_version, feature_snapshot, status
            )
            VALUES (
              :merchant_id, :product_id, :recommended_discount_pct,
              :rationale, :llm_explanation, :confidence_score,
              :model_version, CAST(:feature_snapshot AS jsonb), 'pending'
            )
            RETURNING
              id, merchant_id, product_id, recommended_discount_pct,
              rationale, llm_explanation, confidence_score, model_version,
              feature_snapshot, status, merchant_edit_pct, created_at, reviewed_at
            """
        ),
        {
            "merchant_id": draft.merchant_id,
            "product_id": draft.product_id,
            "recommended_discount_pct": draft.recommended_discount_pct,
            "rationale": draft.rationale,
            "llm_explanation": llm_explanation,
            "confidence_score": draft.confidence_score,
            "model_version": draft.model_version,
            "feature_snapshot": json.dumps(draft.feature_snapshot),
        },
    )
    recommendation = inserted.mappings().first()
    if recommendation is None:
        raise RuntimeError("Failed to insert recommendation")

    await _append_event(
        db, merchant_id, "recommendation_generated",
        {
            "recommendation_id": int(recommendation["id"]),
            "product_id": product_id,
            "recommended_discount_pct": float(recommendation["recommended_discount_pct"]),
            "confidence_score": float(recommendation["confidence_score"]),
            "model_version": recommendation["model_version"],
            "engine_version": engine_version,
            "auto_approve_eligible": auto_approve_eligible,
        },
    )
    await db.commit()

    serialized = _serialize_recommendation(recommendation)
    serialized["product_title"] = str(product["title"])
    return serialized


async def _check_auto_approve(
    db: AsyncSession,
    merchant_id: int,
    product_id: int,
    recommended_pct: float,
    merchant: dict[str, Any],
) -> bool:
    """
    Return True if this recommendation qualifies for auto-approve:
      1. Merchant has auto_approve_enabled = true
      2. Product trust_score >= 0.70
      3. Recommended change is ≤ 5% delta from last approved discount
      4. No active experiment currently running for this product
    """
    # Gate 1: merchant setting
    if not merchant.get("auto_approve_enabled", False):
        return False

    # Gate 2: trust score threshold
    trust = await get_trust_score(db, merchant_id, product_id)
    if trust["trust_score"] < _AUTO_APPROVE_THRESHOLD:
        return False

    # Gate 3: delta from last approved discount
    last_approved = await db.execute(
        text(
            """
            SELECT COALESCE(merchant_edit_pct, recommended_discount_pct)::float AS applied_pct
            FROM recommendations
            WHERE merchant_id = :mid AND product_id = :pid
              AND status IN ('approved', 'edited_and_approved')
            ORDER BY reviewed_at DESC
            LIMIT 1
            """
        ),
        {"mid": merchant_id, "pid": product_id},
    )
    row = last_approved.mappings().first()
    if row:
        last_pct = float(row["applied_pct"])
        if abs(recommended_pct - last_pct) > 5.0:
            return False

    # Gate 4: no active experiment
    active_exp = await db.execute(
        text(
            """
            SELECT 1 FROM experiments
            WHERE product_id = :pid AND status = 'active'
            LIMIT 1
            """
        ),
        {"pid": product_id},
    )
    if active_exp.first() is not None:
        return False

    return True


async def approve_recommendation(
    db: AsyncSession,
    recommendation_id: int,
    shopify_discount_id: str,
    applied_discount_pct: float | None = None,
) -> dict[str, Any]:
    recommendation = await _get_recommendation_by_id(db, recommendation_id)
    applied_pct = applied_discount_pct or float(recommendation["recommended_discount_pct"])

    result = await db.execute(
        text(
            """
            UPDATE recommendations
            SET status = 'approved',
                reviewed_at = NOW()
            WHERE id = :recommendation_id
            RETURNING
              id,
              merchant_id,
              product_id,
              recommended_discount_pct,
              rationale,
              llm_explanation,
              confidence_score,
              model_version,
              feature_snapshot,
              status,
              merchant_edit_pct,
              created_at,
              reviewed_at
            """
        ),
        {"recommendation_id": recommendation_id},
    )
    updated = result.mappings().first()
    if updated is None:
        raise RuntimeError("Recommendation update failed")

    await _append_event(
        db,
        int(updated["merchant_id"]),
        "recommendation_approved",
        {
            "recommendation_id": recommendation_id,
            "product_id": int(updated["product_id"]),
            "approved_discount_pct": applied_pct,
            "shopify_discount_id": shopify_discount_id,
        },
    )
    return _serialize_recommendation(updated)


async def reject_recommendation(
    db: AsyncSession,
    recommendation_id: int,
    reason: str | None,
) -> dict[str, Any]:
    await _get_recommendation_by_id(db, recommendation_id)
    result = await db.execute(
        text(
            """
            UPDATE recommendations
            SET status = 'rejected',
                reviewed_at = NOW()
            WHERE id = :recommendation_id
            RETURNING
              id,
              merchant_id,
              product_id,
              recommended_discount_pct,
              rationale,
              llm_explanation,
              confidence_score,
              model_version,
              feature_snapshot,
              status,
              merchant_edit_pct,
              created_at,
              reviewed_at
            """
        ),
        {"recommendation_id": recommendation_id},
    )
    updated = result.mappings().first()
    if updated is None:
        raise RuntimeError("Recommendation update failed")

    await _append_event(
        db,
        int(updated["merchant_id"]),
        "recommendation_rejected",
        {
            "recommendation_id": recommendation_id,
            "product_id": int(updated["product_id"]),
            "reason": reason or "",
        },
    )
    return _serialize_recommendation(updated)


async def edit_and_approve_recommendation(
    db: AsyncSession,
    recommendation_id: int,
    merchant_edit_pct: float,
    shopify_discount_id: str,
) -> dict[str, Any]:
    await _get_recommendation_by_id(db, recommendation_id)
    result = await db.execute(
        text(
            """
            UPDATE recommendations
            SET status = 'edited_and_approved',
                merchant_edit_pct = :merchant_edit_pct,
                reviewed_at = NOW()
            WHERE id = :recommendation_id
            RETURNING
              id,
              merchant_id,
              product_id,
              recommended_discount_pct,
              rationale,
              llm_explanation,
              confidence_score,
              model_version,
              feature_snapshot,
              status,
              merchant_edit_pct,
              created_at,
              reviewed_at
            """
        ),
        {
            "recommendation_id": recommendation_id,
            "merchant_edit_pct": merchant_edit_pct,
        },
    )
    updated = result.mappings().first()
    if updated is None:
        raise RuntimeError("Recommendation update failed")

    await _append_event(
        db,
        int(updated["merchant_id"]),
        "recommendation_edited",
        {
            "recommendation_id": recommendation_id,
            "product_id": int(updated["product_id"]),
            "recommended_discount_pct": float(updated["recommended_discount_pct"]),
            "merchant_edit_pct": merchant_edit_pct,
        },
    )
    await _append_event(
        db,
        int(updated["merchant_id"]),
        "recommendation_approved",
        {
            "recommendation_id": recommendation_id,
            "product_id": int(updated["product_id"]),
            "approved_discount_pct": merchant_edit_pct,
            "shopify_discount_id": shopify_discount_id,
            "edited": True,
        },
    )
    return _serialize_recommendation(updated)


async def _get_merchant(db: AsyncSession, merchant_id: int) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id, safe_zone_max_pct, active_engine_version
            FROM merchants
            WHERE id = :merchant_id
            """
        ),
        {"merchant_id": merchant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError(f"Merchant {merchant_id} not found")
    return dict(row)


async def _get_product(db: AsyncSession, merchant_id: int, product_id: int) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id, title
            FROM products
            WHERE id = :product_id
              AND merchant_id = :merchant_id
            """
        ),
        {"merchant_id": merchant_id, "product_id": product_id},
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError(f"Product {product_id} not found for merchant {merchant_id}")
    return dict(row)


async def _get_recommendation_by_id(db: AsyncSession, recommendation_id: int) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT
              id,
              merchant_id,
              product_id,
              recommended_discount_pct,
              rationale,
              llm_explanation,
              confidence_score,
              model_version,
              feature_snapshot,
              status,
              merchant_edit_pct,
              created_at,
              reviewed_at
            FROM recommendations
            WHERE id = :recommendation_id
            """
        ),
        {"recommendation_id": recommendation_id},
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError(f"Recommendation {recommendation_id} not found")
    return dict(row)


async def _append_event(
    db: AsyncSession,
    merchant_id: int,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO event_log (merchant_id, event_type, payload)
            VALUES (:merchant_id, :event_type, CAST(:payload AS jsonb))
            """
        ),
        {
            "merchant_id": merchant_id,
            "event_type": event_type,
            "payload": json.dumps(payload),
        },
    )


def _serialize_recommendation(row: Any) -> dict[str, Any]:
    feature_snapshot = row["feature_snapshot"]
    if isinstance(feature_snapshot, str):
        feature_snapshot = json.loads(feature_snapshot)
    return {
        "id": int(row["id"]),
        "merchant_id": int(row["merchant_id"]),
        "product_id": int(row["product_id"]),
        "recommended_discount_pct": float(row["recommended_discount_pct"]),
        "rationale": str(row["rationale"]),
        "llm_explanation": str(row["llm_explanation"] or row["rationale"]),
        "confidence_score": float(row["confidence_score"]),
        "model_version": str(row["model_version"]),
        "feature_snapshot": feature_snapshot or {},
        "status": str(row["status"]),
        "merchant_edit_pct": (
            float(row["merchant_edit_pct"])
            if row["merchant_edit_pct"] is not None
            else None
        ),
        "created_at": row["created_at"].isoformat(),
        "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
    }
