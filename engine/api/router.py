from fastapi import APIRouter

from engine.api import features, health, recommendations

api_router = APIRouter()

# Ops
api_router.include_router(health.router)

# Phase 2A: feature vectors
api_router.include_router(features.router)

api_router.include_router(recommendations.router, tags=["recommendations"])
