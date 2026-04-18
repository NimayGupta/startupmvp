"""
Phase 4 — Experiment Service

CRUD operations and Bayesian monitoring for A/B discount experiments.

Each experiment compares:
  Control   — product at its historical baseline rate (14-day pre-period)
  Treatment — product with the recommended discount applied via Shopify Function

Statistical model: Gamma-Poisson (see engine/stats/bayesian.py).
All mutations are logged to event_log for audit.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from engine.bandit.thompson import ACTIONS, compute_context_bucket, update_bandit_params
from engine.engine_selector import maybe_promote_to_bandit
from engine.stats.bayesian import ExperimentStats, compute_experiment_stats
from engine.trust.scorer import update_trust_score

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def create_experiment(
    db: AsyncSession,
    merchant_id: int,
    product_id: int,
    recommendation_id: int,
    control_discount_pct: float,
    treatment_discount_pct: float,
    shopify_discount_id: str,
) -> dict[str, Any]:
    """
    Insert a new active experiment and immediately start it.

    The Shopify discount (shopify_discount_id) has already been created by
    the Remix app before this is called.
    """
    result = await db.execute(
        text(
            """
            INSERT INTO experiments (
              merchant_id, product_id, recommendation_id,
              control_discount_pct, treatment_discount_pct,
              shopify_discount_id, status, started_at
            )
            VALUES (
              :merchant_id, :product_id, :recommendation_id,
              :control_discount_pct, :treatment_discount_pct,
              :shopify_discount_id, 'active', NOW()
            )
            RETURNING
              id, merchant_id, product_id, recommendation_id,
              status, control_discount_pct, treatment_discount_pct,
              shopify_discount_id, started_at, concluded_at,
              conclusion_type, latest_stats, created_at
            """
        ),
        {
            "merchant_id": merchant_id,
            "product_id": product_id,
            "recommendation_id": recommendation_id,
            "control_discount_pct": control_discount_pct,
            "treatment_discount_pct": treatment_discount_pct,
            "shopify_discount_id": shopify_discount_id,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise RuntimeError("Failed to insert experiment")

    await _append_event(
        db,
        merchant_id,
        "experiment_created",
        {
            "experiment_id": int(row["id"]),
            "product_id": product_id,
            "recommendation_id": recommendation_id,
            "control_discount_pct": control_discount_pct,
            "treatment_discount_pct": treatment_discount_pct,
        },
    )
    await db.commit()
    return _serialize_experiment(row)


async def get_experiment(
    db: AsyncSession,
    experiment_id: int,
) -> dict[str, Any] | None:
    """Fetch a single experiment by primary key."""
    result = await db.execute(
        text(
            """
            SELECT
              id, merchant_id, product_id, recommendation_id,
              status, control_discount_pct, treatment_discount_pct,
              shopify_discount_id, started_at, concluded_at,
              conclusion_type, latest_stats, created_at
            FROM experiments
            WHERE id = :experiment_id
            """
        ),
        {"experiment_id": experiment_id},
    )
    row = result.mappings().first()
    return _serialize_experiment(row) if row else None


async def kill_experiment(
    db: AsyncSession,
    experiment_id: int,
    merchant_id: int,
) -> dict[str, Any]:
    """
    Manually kill an active experiment (merchant override).
    Sets status='killed', conclusion_type='kill_switch'.
    """
    result = await db.execute(
        text(
            """
            UPDATE experiments
            SET status = 'killed',
                conclusion_type = 'kill_switch',
                concluded_at = NOW()
            WHERE id = :experiment_id
              AND merchant_id = :merchant_id
              AND status = 'active'
            RETURNING
              id, merchant_id, product_id, recommendation_id,
              status, control_discount_pct, treatment_discount_pct,
              shopify_discount_id, started_at, concluded_at,
              conclusion_type, latest_stats, created_at
            """
        ),
        {"experiment_id": experiment_id, "merchant_id": merchant_id},
    )
    row = result.mappings().first()
    if row is None:
        raise ValueError(
            f"Experiment {experiment_id} not found or not active for merchant {merchant_id}"
        )

    await _append_event(
        db,
        merchant_id,
        "experiment_killed",
        {
            "experiment_id": experiment_id,
            "product_id": int(row["product_id"]),
            "conclusion_type": "kill_switch",
        },
    )
    await db.commit()
    return _serialize_experiment(row)


async def monitor_merchant_experiments(
    db: AsyncSession,
    merchant_id: int,
) -> dict[str, Any]:
    """
    Refresh Bayesian stats for all active experiments belonging to a merchant.

    For each active experiment:
      1. Query order_line_items for control (14-day pre-period) and treatment
         (post-activation) windows.
      2. Compute stats via Gamma-Poisson Bayesian model.
      3. Persist latest_stats to the experiments table.
      4. Auto-conclude if significance or kill-switch threshold is met.
      5. Log events to event_log.

    Returns a summary dict: {monitored, concluded, kill_switched}.
    """
    active_experiments = await _get_active_experiments(db, merchant_id)

    summary: dict[str, Any] = {
        "merchant_id": merchant_id,
        "monitored": len(active_experiments),
        "concluded": 0,
        "kill_switched": 0,
    }

    for exp in active_experiments:
        experiment_id = int(exp["id"])
        product_id = int(exp["product_id"])
        started_at: datetime = exp["started_at"]

        # Fetch aggregate order data for both experiment windows
        data = await _fetch_experiment_order_data(db, merchant_id, product_id, started_at)
        stats = compute_experiment_stats(
            experiment_id=experiment_id,
            control_orders=data["control_orders"],
            control_days=data["control_days"],
            treatment_orders=data["treatment_orders"],
            treatment_days=data["treatment_days"],
            control_revenue=data["control_revenue"],
            treatment_revenue=data["treatment_revenue"],
            days_running=data["days_running"],
        )

        # Determine if the experiment should conclude
        new_status: str | None = None
        conclusion_type: str | None = None
        if stats.kill_switch_triggered and data["treatment_days"] >= 3:
            new_status = "killed"
            conclusion_type = "kill_switch"
            summary["kill_switched"] += 1
        elif stats.significance_reached and data["treatment_days"] >= 3:
            new_status = "concluded"
            conclusion_type = "significance_reached"
            summary["concluded"] += 1
        elif data["treatment_days"] >= 30:
            new_status = "concluded"
            conclusion_type = "max_duration"
            summary["concluded"] += 1

        await _update_experiment_stats(
            db,
            experiment_id=experiment_id,
            merchant_id=merchant_id,
            stats=stats,
            new_status=new_status,
            conclusion_type=conclusion_type,
        )

        # On conclusion: update trust score + bandit posterior (Phase 5)
        if new_status is not None:
            experiment_positive = stats.prob_treatment_better > 0.70
            await update_trust_score(
                db, merchant_id, product_id,
                experiment_positive=experiment_positive,
                commit=False,
            )
            await _update_bandit_on_conclusion(
                db, merchant_id, product_id, exp, stats, experiment_positive
            )
            await maybe_promote_to_bandit(db, merchant_id, commit=False)

        await db.commit()

    return summary


async def _update_bandit_on_conclusion(
    db: AsyncSession,
    merchant_id: int,
    product_id: int,
    exp: Any,
    stats: ExperimentStats,
    experiment_positive: bool,
) -> None:
    """
    After an experiment concludes, update the bandit posterior for the
    (context_bucket, action) pair that was tested.

    Context bucket: read from the linked recommendation's feature_snapshot.
    Action: treatment_discount_pct rounded to the nearest valid action level.
    """
    treatment_pct = float(exp.get("treatment_discount_pct", 0))
    action = min(ACTIONS, key=lambda a: abs(a - treatment_pct))

    # Try to read context_bucket from the recommendation's feature_snapshot
    context_bucket: str | None = None
    rec_result = await db.execute(
        text(
            """
            SELECT r.feature_snapshot
            FROM recommendations r
            JOIN experiments e ON e.recommendation_id = r.id
            WHERE e.id = :exp_id
            LIMIT 1
            """
        ),
        {"exp_id": int(exp["id"])},
    )
    rec_row = rec_result.mappings().first()
    if rec_row and rec_row["feature_snapshot"]:
        snap = rec_row["feature_snapshot"]
        if isinstance(snap, str):
            import json as _json
            snap = _json.loads(snap)
        context_bucket = snap.get("context_bucket")

    if not context_bucket:
        logger.warning(
            "Cannot update bandit: no context_bucket for experiment %d", int(exp["id"])
        )
        return

    reward = 1.0 if experiment_positive else 0.0
    await update_bandit_params(
        db, merchant_id=merchant_id, context_bucket=context_bucket,
        action=action, reward=reward, commit=False,
    )
    logger.info(
        "Bandit updated: merchant=%d context=%s action=%d reward=%.1f",
        merchant_id, context_bucket, action, reward,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_active_experiments(
    db: AsyncSession,
    merchant_id: int,
) -> list[Any]:
    result = await db.execute(
        text(
            """
            SELECT id, merchant_id, product_id, started_at,
                   shopify_discount_id, treatment_discount_pct
            FROM experiments
            WHERE merchant_id = :merchant_id
              AND status = 'active'
            ORDER BY started_at ASC
            """
        ),
        {"merchant_id": merchant_id},
    )
    return list(result.mappings().all())


async def _fetch_experiment_order_data(
    db: AsyncSession,
    merchant_id: int,
    product_id: int,
    started_at: datetime,
) -> dict[str, Any]:
    """
    Returns aggregate order metrics for the control (14-day pre-period) and
    treatment (post-activation) windows.

    The control window is the 14 days immediately before ``started_at``.
    The treatment window runs from ``started_at`` to NOW().
    """
    ctrl_start = started_at - timedelta(days=14)
    result = await db.execute(
        text(
            """
            WITH periods AS (
              SELECT
                COALESCE(SUM(oli.quantity * oli.price) FILTER (
                  WHERE oli.created_at >= :ctrl_start AND oli.created_at < :started_at
                ), 0)::float                                     AS control_revenue,
                COUNT(oli.id) FILTER (
                  WHERE oli.created_at >= :ctrl_start AND oli.created_at < :started_at
                )::int                                           AS control_orders,
                COALESCE(SUM(oli.quantity * oli.price) FILTER (
                  WHERE oli.created_at >= :started_at
                ), 0)::float                                     AS treatment_revenue,
                COUNT(oli.id) FILTER (
                  WHERE oli.created_at >= :started_at
                )::int                                           AS treatment_orders,
                (EXTRACT(EPOCH FROM (NOW() - :started_at)) / 86400)::float AS treatment_days,
                GREATEST(FLOOR(EXTRACT(EPOCH FROM (NOW() - :started_at)) / 86400), 1)::int
                  AS days_running
              FROM order_line_items oli
              JOIN product_variants pv
                ON pv.shopify_variant_id = oli.shopify_variant_id
              WHERE pv.product_id = :product_id
                AND oli.merchant_id = :merchant_id
                AND oli.created_at >= :ctrl_start
            )
            SELECT * FROM periods
            """
        ),
        {
            "merchant_id": merchant_id,
            "product_id": product_id,
            "started_at": started_at,
            "ctrl_start": ctrl_start,
        },
    )
    row = result.mappings().first()
    if row is None:
        return {
            "control_orders": 0,
            "control_days": 14.0,
            "treatment_orders": 0,
            "treatment_days": 1.0,
            "control_revenue": 0.0,
            "treatment_revenue": 0.0,
            "days_running": 0,
        }
    return {
        "control_orders": int(row["control_orders"]),
        "control_days": 14.0,
        "treatment_orders": int(row["treatment_orders"]),
        "treatment_days": max(float(row["treatment_days"]), 0.1),
        "control_revenue": float(row["control_revenue"]),
        "treatment_revenue": float(row["treatment_revenue"]),
        "days_running": int(row["days_running"]),
    }


async def _update_experiment_stats(
    db: AsyncSession,
    experiment_id: int,
    merchant_id: int,
    stats: ExperimentStats,
    new_status: str | None,
    conclusion_type: str | None,
) -> None:
    stats_json = stats.model_dump()
    stats_json["last_computed_at"] = datetime.now(timezone.utc).isoformat()

    if new_status:
        await db.execute(
            text(
                """
                UPDATE experiments
                SET latest_stats   = CAST(:stats AS jsonb),
                    status         = :status,
                    conclusion_type = :conclusion_type,
                    concluded_at   = NOW()
                WHERE id = :experiment_id
                """
            ),
            {
                "experiment_id": experiment_id,
                "stats": json.dumps(stats_json),
                "status": new_status,
                "conclusion_type": conclusion_type,
            },
        )
        event_type = (
            "kill_switch_triggered" if conclusion_type == "kill_switch"
            else "experiment_concluded"
        )
        await _append_event(
            db,
            merchant_id,
            event_type,
            {
                "experiment_id": experiment_id,
                "conclusion_type": conclusion_type,
                "prob_treatment_better": stats.prob_treatment_better,
                "prob_kill_switch": stats.prob_kill_switch,
            },
        )
    else:
        await db.execute(
            text(
                """
                UPDATE experiments
                SET latest_stats = CAST(:stats AS jsonb)
                WHERE id = :experiment_id
                """
            ),
            {
                "experiment_id": experiment_id,
                "stats": json.dumps(stats_json),
            },
        )
        await _append_event(
            db,
            merchant_id,
            "experiment_monitored",
            {
                "experiment_id": experiment_id,
                "prob_treatment_better": stats.prob_treatment_better,
                "prob_kill_switch": stats.prob_kill_switch,
                "days_running": stats.days_running,
            },
        )


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


def _serialize_experiment(row: Any) -> dict[str, Any]:
    latest_stats = row["latest_stats"]
    if isinstance(latest_stats, str):
        latest_stats = json.loads(latest_stats)
    return {
        "id": int(row["id"]),
        "merchant_id": int(row["merchant_id"]),
        "product_id": int(row["product_id"]),
        "recommendation_id": (int(row["recommendation_id"]) if row["recommendation_id"] else None),
        "status": str(row["status"]),
        "control_discount_pct": float(row["control_discount_pct"]),
        "treatment_discount_pct": float(row["treatment_discount_pct"]),
        "shopify_discount_id": str(row["shopify_discount_id"] or ""),
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "concluded_at": row["concluded_at"].isoformat() if row["concluded_at"] else None,
        "conclusion_type": str(row["conclusion_type"]) if row["conclusion_type"] else None,
        "latest_stats": latest_stats,
        "created_at": row["created_at"].isoformat(),
    }
