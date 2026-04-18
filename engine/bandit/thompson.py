"""
Phase 5A — Thompson Sampling Contextual Bandit

Action space: discrete discount levels [0, 5, 10, 15, 20] (%).
Context: (price_tier, inventory_bucket, conversion_bucket) bucketed to a string key.

Thompson Sampling mechanics
---------------------------
For each (context_bucket, action) pair maintain Beta(α, β) — uninformative
prior Beta(1, 1) = Uniform at cold start.

On recommendation: sample θ_a ~ Beta(α_a, β_a) for each action, return
the action with the highest sampled θ.

On reward r ∈ {0, 1}: α_a += r,  β_a += (1 − r).

Persistence: bandit_parameters table (unique on merchant_id, context_bucket, action).
"""
from __future__ import annotations

import logging
import math
from statistics import mean
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from engine.rules.v1 import RecommendationDraft

logger = logging.getLogger(__name__)

# Discrete action space — discount percentages the bandit can choose
ACTIONS: list[int] = [0, 5, 10, 15, 20]

_PRIOR_ALPHA = 1.0
_PRIOR_BETA = 1.0
_RNG_SEED = 42
_rng = np.random.default_rng(_RNG_SEED)


# ---------------------------------------------------------------------------
# Context bucketing
# ---------------------------------------------------------------------------

def compute_context_bucket(features: list[dict[str, Any]]) -> str:
    """
    Map a feature vector list to a discrete context bucket string.

    Format: "{price_tier}_{inventory_bucket}_{conversion_bucket}"
    where each sub-bucket is low | medium | high.
    """
    if not features:
        return "unknown_medium_low"

    price_tier = str(features[0].get("price_tier", "unknown"))
    avg_inventory = mean(float(f["inventory_days_supply"]) for f in features)
    avg_conversion = mean(float(f["conversion_rate"]) for f in features)

    if avg_inventory < 30:
        inv_bucket = "low"
    elif avg_inventory < 90:
        inv_bucket = "medium"
    else:
        inv_bucket = "high"

    if avg_conversion < 0.01:
        conv_bucket = "low"
    elif avg_conversion < 0.05:
        conv_bucket = "medium"
    else:
        conv_bucket = "high"

    return f"{price_tier}_{inv_bucket}_{conv_bucket}"


# ---------------------------------------------------------------------------
# DB I/O
# ---------------------------------------------------------------------------

async def load_bandit_params(
    db: AsyncSession,
    merchant_id: int,
    context_bucket: str,
) -> dict[int, tuple[float, float]]:
    """
    Load (alpha, beta) for each action from DB.
    Returns the Beta(1,1) prior for actions with no observations yet.
    """
    result = await db.execute(
        text(
            """
            SELECT action, alpha::float, beta::float
            FROM bandit_parameters
            WHERE merchant_id = :merchant_id
              AND context_bucket = :context_bucket
            """
        ),
        {"merchant_id": merchant_id, "context_bucket": context_bucket},
    )
    rows = {int(r["action"]): (float(r["alpha"]), float(r["beta"])) for r in result.mappings()}
    return {a: rows.get(a, (_PRIOR_ALPHA, _PRIOR_BETA)) for a in ACTIONS}


async def update_bandit_params(
    db: AsyncSession,
    merchant_id: int,
    context_bucket: str,
    action: int,
    reward: float,
    commit: bool = True,
) -> None:
    """
    Upsert bandit parameters for one (context_bucket, action) pair.
    reward ∈ [0, 1].  Fractional rewards are supported (for soft signals).
    """
    await db.execute(
        text(
            """
            INSERT INTO bandit_parameters
              (merchant_id, context_bucket, action, alpha, beta, observations)
            VALUES
              (:merchant_id, :context_bucket, :action,
               CAST(:init_alpha AS numeric) + CAST(:reward AS numeric),
               CAST(:init_beta  AS numeric) + CAST(:neg_reward AS numeric), 1)
            ON CONFLICT (merchant_id, context_bucket, action) DO UPDATE
              SET alpha        = bandit_parameters.alpha + CAST(:reward AS numeric),
                  beta         = bandit_parameters.beta  + CAST(:neg_reward AS numeric),
                  observations = bandit_parameters.observations + 1,
                  updated_at   = NOW()
            """
        ),
        {
            "merchant_id": merchant_id,
            "context_bucket": context_bucket,
            "action": action,
            "init_alpha": _PRIOR_ALPHA,
            "init_beta": _PRIOR_BETA,
            "reward": float(reward),
            "neg_reward": 1.0 - float(reward),
        },
    )
    if commit:
        await db.commit()


async def reset_bandit_params(
    db: AsyncSession,
    merchant_id: int,
) -> None:
    """Delete all bandit parameters for a merchant (before retraining replay)."""
    await db.execute(
        text("DELETE FROM bandit_parameters WHERE merchant_id = :merchant_id"),
        {"merchant_id": merchant_id},
    )


# ---------------------------------------------------------------------------
# Thompson Sampling
# ---------------------------------------------------------------------------

def sample_action(params: dict[int, tuple[float, float]]) -> int:
    """
    Thompson sample: draw θ_a ~ Beta(α_a, β_a) for each action.
    Return the action with the highest sampled θ.
    """
    sampled = {a: float(_rng.beta(alpha, beta)) for a, (alpha, beta) in params.items()}
    return max(sampled, key=lambda a: sampled[a])


# ---------------------------------------------------------------------------
# Recommendation generation
# ---------------------------------------------------------------------------

async def generate_bandit_recommendation(
    db: AsyncSession,
    merchant_id: int,
    product_id: int,
    safe_zone_max_pct: float,
    features: list[dict[str, Any]],
) -> RecommendationDraft:
    """
    Generate a discount recommendation using Thompson Sampling.

    Returns a RecommendationDraft with model_version='bandit_v1', compatible
    with the rules engine's interface so callers need no special-casing.
    """
    context_bucket = compute_context_bucket(features)
    params = await load_bandit_params(db, merchant_id, context_bucket)
    chosen_action = sample_action(params)
    recommended_pct = min(float(chosen_action), safe_zone_max_pct)

    # Confidence grows with logged total observations across all actions
    total_obs = sum(
        max(0, round(alpha + beta - _PRIOR_ALPHA - _PRIOR_BETA))
        for alpha, beta in params.values()
    )
    confidence = min(0.50 + math.log1p(total_obs) * 0.05, 0.95)

    alpha_a, beta_a = params[chosen_action]
    obs_action = max(0, round(alpha_a + beta_a - _PRIOR_ALPHA - _PRIOR_BETA))

    rationale = (
        f"Bandit v1 selected {chosen_action}% discount via Thompson Sampling "
        f"across {total_obs} total observations in context '{context_bucket}'. "
        f"This action has α={alpha_a:.2f}, β={beta_a:.2f} ({obs_action} observations)."
    )

    snapshot: dict[str, Any] = {
        "model_version": "bandit_v1",
        "context_bucket": context_bucket,
        "action_selected": chosen_action,
        "total_observations": total_obs,
        "action_observations": obs_action,
        "params": {
            str(a): {"alpha": round(al, 4), "beta": round(be, 4)}
            for a, (al, be) in params.items()
        },
    }

    return RecommendationDraft(
        merchant_id=merchant_id,
        product_id=product_id,
        recommended_discount_pct=round(recommended_pct, 2),
        confidence_score=round(confidence, 3),
        rationale=rationale,
        feature_snapshot=snapshot,
        model_version="bandit_v1",
    )
