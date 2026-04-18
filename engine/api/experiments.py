"""
Phase 4 — Experiments API

Endpoints for creating, querying, killing, and monitoring A/B experiments.

All routes are protected by RequireInternalAuth (Bearer INTERNAL_API_KEY).
The Remix app calls these endpoints; the Celery worker calls /monitor.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from engine.api.billing import enforce_experiment_limit
from engine.api.deps import DbSession, RequireInternalAuth
from engine.experiments.service import (
    create_experiment,
    get_experiment,
    kill_experiment,
    monitor_merchant_experiments,
)

router = APIRouter(prefix="/experiments")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateExperimentRequest(BaseModel):
    merchant_id: int
    product_id: int
    recommendation_id: int | None = None
    control_discount_pct: float
    treatment_discount_pct: float
    shopify_discount_id: str


class KillExperimentRequest(BaseModel):
    merchant_id: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", dependencies=[RequireInternalAuth])
async def create_experiment_endpoint(
    body: CreateExperimentRequest,
    db: DbSession,
) -> dict[str, Any]:
    """
    Create and immediately activate a new A/B experiment.

    The Shopify discount (``shopify_discount_id``) must be created by the
    caller before calling this endpoint.  The experiment starts as ``active``
    with ``started_at = NOW()``.
    """
    await enforce_experiment_limit(db, body.merchant_id)
    return await create_experiment(
        db=db,
        merchant_id=body.merchant_id,
        product_id=body.product_id,
        recommendation_id=body.recommendation_id,
        control_discount_pct=body.control_discount_pct,
        treatment_discount_pct=body.treatment_discount_pct,
        shopify_discount_id=body.shopify_discount_id,
    )


@router.get("/{experiment_id}", dependencies=[RequireInternalAuth])
async def get_experiment_endpoint(
    experiment_id: int,
    db: DbSession,
) -> dict[str, Any]:
    """Fetch a single experiment by its primary key."""
    exp = await get_experiment(db, experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp


@router.post("/{experiment_id}/kill", dependencies=[RequireInternalAuth])
async def kill_experiment_endpoint(
    experiment_id: int,
    body: KillExperimentRequest,
    db: DbSession,
) -> dict[str, Any]:
    """
    Manually kill an active experiment (merchant-initiated override).

    Sets ``status = 'killed'``, ``conclusion_type = 'kill_switch'``,
    and writes a ``experiment_killed`` event to event_log.
    """
    try:
        return await kill_experiment(db, experiment_id, body.merchant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/monitor/{merchant_id}", dependencies=[RequireInternalAuth])
async def monitor_experiments_endpoint(
    merchant_id: int,
    db: DbSession,
) -> dict[str, Any]:
    """
    Refresh Bayesian statistics for all active experiments of a merchant.

    Called every 6 hours by the Celery beat task
    ``workers.tasks.experiment_monitor.monitor_all_merchants``.

    Returns a summary: ``{merchant_id, monitored, concluded, kill_switched}``.
    """
    return await monitor_merchant_experiments(db, merchant_id)
