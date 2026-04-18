"""
Phase 5C — Bandit Retraining API

POST /bandit/retrain/{merchant_id}
  Called by the weekly Celery beat task.
  Replays the last 30 days of experiment outcomes to rebuild the bandit
  posterior, then applies soft signals from recommendation edits/rejections.

GET  /bandit/{merchant_id}/params
  Returns current bandit parameters for debugging / dashboard display.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from engine.api.deps import DbSession, RequireInternalAuth
from engine.bandit.thompson import (
    ACTIONS,
    _PRIOR_ALPHA,
    _PRIOR_BETA,
    compute_context_bucket,
    reset_bandit_params,
    update_bandit_params,
)
from engine.engine_selector import maybe_promote_to_bandit
from engine.trust.scorer import update_trust_score

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bandit")


# ---------------------------------------------------------------------------
# Retrain endpoint
# ---------------------------------------------------------------------------


@router.post("/retrain/{merchant_id}", dependencies=[RequireInternalAuth])
async def retrain_merchant(merchant_id: int, db: DbSession) -> dict[str, Any]:
    """
    Rebuild bandit posterior from the last 30 days of experiment outcomes
    and soft signals (edits, rejections).

    Steps
    -----
    1. Pull experiment_concluded events → hard rewards.
    2. Pull recommendation_edited events → soft nudge (reward=0.5).
    3. Pull recommendation_rejected events → soft penalty (reward=0).
    4. Reset existing bandit parameters for this merchant.
    5. Replay all observations in chronological order.
    6. Log model_retrained event.
    7. Maybe promote merchant to bandit_v1 if threshold reached.
    """
    since = datetime.now(timezone.utc) - timedelta(days=30)

    # ------------------------------------------------------------------
    # 1. Hard rewards: concluded experiments
    # ------------------------------------------------------------------
    concluded = await db.execute(
        text(
            """
            SELECT el.payload,
                   e.treatment_discount_pct::float AS action_pct,
                   e.product_id,
                   r.feature_snapshot
            FROM event_log el
            JOIN experiments e ON (el.payload->>'experiment_id')::bigint = e.id
            LEFT JOIN recommendations r ON e.recommendation_id = r.id
            WHERE el.merchant_id  = :mid
              AND el.event_type   = 'experiment_concluded'
              AND el.created_at  >= :since
            ORDER BY el.created_at ASC
            """
        ),
        {"mid": merchant_id, "since": since},
    )

    observations: list[dict[str, Any]] = []
    for row in concluded.mappings():
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        prob = float(payload.get("prob_treatment_better", 0.5))
        reward = 1.0 if prob > 0.70 else 0.0

        feature_snap = row["feature_snapshot"]
        if isinstance(feature_snap, str):
            feature_snap = json.loads(feature_snap) if feature_snap else {}

        # Derive context from the recommendation's feature_snapshot if available
        context_bucket = str(feature_snap.get("context_bucket", ""))
        if not context_bucket:
            # Fall back: we can't reconstruct context without features
            logger.warning(
                "No context_bucket in feature_snapshot for experiment; skipping"
            )
            continue

        action_pct = float(row["action_pct"])
        # Round to nearest valid action
        action = min(ACTIONS, key=lambda a: abs(a - action_pct))

        observations.append({
            "context_bucket": context_bucket,
            "action": action,
            "reward": reward,
            "type": "hard",
        })

    # ------------------------------------------------------------------
    # 2. Soft nudge: recommendation edits (merchant increased discount)
    # ------------------------------------------------------------------
    edited = await db.execute(
        text(
            """
            SELECT el.payload, r.feature_snapshot
            FROM event_log el
            JOIN recommendations r ON (el.payload->>'recommendation_id')::bigint = r.id
            WHERE el.merchant_id = :mid
              AND el.event_type  = 'recommendation_edited'
              AND el.created_at >= :since
            ORDER BY el.created_at ASC
            """
        ),
        {"mid": merchant_id, "since": since},
    )
    for row in edited.mappings():
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        rec_pct = float(payload.get("recommended_discount_pct", 0))
        edit_pct = float(payload.get("merchant_edit_pct", rec_pct))

        feature_snap = row["feature_snapshot"]
        if isinstance(feature_snap, str):
            feature_snap = json.loads(feature_snap) if feature_snap else {}
        context_bucket = str(feature_snap.get("context_bucket", ""))
        if not context_bucket:
            continue

        if edit_pct > rec_pct:
            # Merchant thought the recommendation was too conservative —
            # nudge the next higher action with a partial positive reward.
            rec_action = min(ACTIONS, key=lambda a: abs(a - rec_pct))
            idx = ACTIONS.index(rec_action)
            next_action = ACTIONS[min(idx + 1, len(ACTIONS) - 1)]
            observations.append({
                "context_bucket": context_bucket,
                "action": next_action,
                "reward": 0.5,   # soft positive nudge
                "type": "soft_edit_up",
            })
        # If edited down, we treat it as a soft negative for the original action
        else:
            rec_action = min(ACTIONS, key=lambda a: abs(a - rec_pct))
            observations.append({
                "context_bucket": context_bucket,
                "action": rec_action,
                "reward": 0.3,   # slight penalty — merchant preferred less
                "type": "soft_edit_down",
            })

    # ------------------------------------------------------------------
    # 3. Soft penalty: rejections
    # ------------------------------------------------------------------
    rejected = await db.execute(
        text(
            """
            SELECT el.payload, r.feature_snapshot,
                   r.recommended_discount_pct::float AS rec_pct
            FROM event_log el
            JOIN recommendations r ON (el.payload->>'recommendation_id')::bigint = r.id
            WHERE el.merchant_id = :mid
              AND el.event_type  = 'recommendation_rejected'
              AND el.created_at >= :since
            ORDER BY el.created_at ASC
            """
        ),
        {"mid": merchant_id, "since": since},
    )
    for row in rejected.mappings():
        feature_snap = row["feature_snapshot"]
        if isinstance(feature_snap, str):
            feature_snap = json.loads(feature_snap) if feature_snap else {}
        context_bucket = str(feature_snap.get("context_bucket", ""))
        if not context_bucket:
            continue
        rec_action = min(ACTIONS, key=lambda a: abs(a - float(row["rec_pct"])))
        observations.append({
            "context_bucket": context_bucket,
            "action": rec_action,
            "reward": 0.0,   # hard negative — merchant rejected outright
            "type": "soft_reject",
        })

    # ------------------------------------------------------------------
    # 4. Reset parameters, replay observations
    # ------------------------------------------------------------------
    await reset_bandit_params(db, merchant_id)

    for obs in observations:
        await update_bandit_params(
            db,
            merchant_id=merchant_id,
            context_bucket=obs["context_bucket"],
            action=obs["action"],
            reward=obs["reward"],
            commit=False,
        )

    # ------------------------------------------------------------------
    # 5. Log model_retrained event
    # ------------------------------------------------------------------
    summary = {
        "hard_observations": sum(1 for o in observations if o["type"] == "hard"),
        "soft_edits": sum(1 for o in observations if o["type"].startswith("soft_edit")),
        "soft_rejections": sum(1 for o in observations if o["type"] == "soft_reject"),
        "total_observations": len(observations),
    }
    await db.execute(
        text(
            """
            INSERT INTO event_log (merchant_id, event_type, payload)
            VALUES (:mid, 'model_retrained', CAST(:payload AS jsonb))
            """
        ),
        {"mid": merchant_id, "payload": json.dumps(summary)},
    )
    await db.commit()

    # ------------------------------------------------------------------
    # 6. Maybe promote to bandit_v1
    # ------------------------------------------------------------------
    promoted = await maybe_promote_to_bandit(db, merchant_id)

    logger.info(
        "Retrain complete for merchant %d: %d observations, promoted=%s",
        merchant_id, len(observations), promoted,
    )
    return {
        "merchant_id": merchant_id,
        "promoted_to_bandit": promoted,
        **summary,
    }


# ---------------------------------------------------------------------------
# Debug / dashboard: current parameters
# ---------------------------------------------------------------------------


@router.get("/{merchant_id}/params", dependencies=[RequireInternalAuth])
async def get_bandit_params(merchant_id: int, db: DbSession) -> dict[str, Any]:
    """Return all bandit parameters for a merchant (grouped by context_bucket)."""
    result = await db.execute(
        text(
            """
            SELECT context_bucket, action, alpha::float, beta::float, observations
            FROM bandit_parameters
            WHERE merchant_id = :mid
            ORDER BY context_bucket, action
            """
        ),
        {"mid": merchant_id},
    )
    rows = list(result.mappings())
    by_context: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        cb = str(r["context_bucket"])
        by_context.setdefault(cb, []).append({
            "action": int(r["action"]),
            "alpha": round(float(r["alpha"]), 4),
            "beta": round(float(r["beta"]), 4),
            "observations": int(r["observations"]),
            "mean_reward": round(
                (float(r["alpha"]) - _PRIOR_ALPHA)
                / max(float(r["alpha"]) + float(r["beta"]) - _PRIOR_ALPHA - _PRIOR_BETA, 1),
                4,
            ),
        })
    return {"merchant_id": merchant_id, "contexts": by_context}
