from fastapi import APIRouter

from engine.api import features, health

api_router = APIRouter()

# Ops
api_router.include_router(health.router)

# Phase 2A: feature vectors
api_router.include_router(features.router)

# Phase 3+: recommendations router added here when implemented
# from engine.api import recommendations
# api_router.include_router(recommendations.router, prefix="/recommendations", tags=["recommendations"])
