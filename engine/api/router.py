from fastapi import APIRouter

from engine.api import bandit, experiments, features, health, recommendations, trust

api_router = APIRouter()

# Ops
api_router.include_router(health.router)

# Phase 2A: feature vectors
api_router.include_router(features.router)

# Phase 3: recommendations
api_router.include_router(recommendations.router, tags=["recommendations"])

# Phase 4: A/B experiments
api_router.include_router(experiments.router, tags=["experiments"])

# Phase 5: bandit retraining + trust scores
api_router.include_router(bandit.router, tags=["bandit"])
api_router.include_router(trust.router, tags=["trust"])
