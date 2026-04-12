"""
Phase 3C - Recommendations API.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from engine.api.deps import DbSession, RequireInternalAuth
from engine.recommendations.service import (
    approve_recommendation,
    edit_and_approve_recommendation,
    generate_or_get_recommendation,
    get_latest_recommendation,
    reject_recommendation,
)

router = APIRouter(prefix="/recommendations")


class GenerateRecommendationRequest(BaseModel):
    merchant_id: int
    product_id: int


class ApproveRecommendationRequest(BaseModel):
    shopify_discount_id: str
    applied_discount_pct: float | None = None


class RejectRecommendationRequest(BaseModel):
    reason: str | None = None


class EditApproveRecommendationRequest(BaseModel):
    merchant_edit_pct: float = Field(ge=0, le=100)
    shopify_discount_id: str


@router.get(
    "/{merchant_id}/products/{product_id}",
    dependencies=[RequireInternalAuth],
)
async def latest_recommendation(
    merchant_id: int,
    product_id: int,
    db: DbSession,
) -> dict[str, Any]:
    recommendation = await get_latest_recommendation(db, merchant_id, product_id)
    if recommendation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    return recommendation


@router.post(
    "/generate",
    dependencies=[RequireInternalAuth],
)
async def create_recommendation(
    payload: GenerateRecommendationRequest,
    db: DbSession,
) -> dict[str, Any]:
    try:
        return await generate_or_get_recommendation(db, payload.merchant_id, payload.product_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{recommendation_id}/approve",
    dependencies=[RequireInternalAuth],
)
async def approve(
    recommendation_id: int,
    payload: ApproveRecommendationRequest,
    db: DbSession,
) -> dict[str, Any]:
    try:
        return await approve_recommendation(
            db,
            recommendation_id,
            payload.shopify_discount_id,
            payload.applied_discount_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{recommendation_id}/reject",
    dependencies=[RequireInternalAuth],
)
async def reject(
    recommendation_id: int,
    payload: RejectRecommendationRequest,
    db: DbSession,
) -> dict[str, Any]:
    try:
        return await reject_recommendation(db, recommendation_id, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{recommendation_id}/edit-approve",
    dependencies=[RequireInternalAuth],
)
async def edit_approve(
    recommendation_id: int,
    payload: EditApproveRecommendationRequest,
    db: DbSession,
) -> dict[str, Any]:
    try:
        return await edit_and_approve_recommendation(
            db,
            recommendation_id,
            payload.merchant_edit_pct,
            payload.shopify_discount_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
