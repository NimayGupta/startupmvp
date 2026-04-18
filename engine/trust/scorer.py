"""
Phase 5E — Per-Product Trust Score Computation

Trust score formula
-------------------
  score = (tests_positive / tests_completed) × log1p(tests_completed) / log1p(10)
  Capped at 1.0.  Zero until minimum 3 completed tests.

Interpretation
  0.0       — not yet eligible (< 3 tests)
  0.0–0.7   — learning, manual review required
  0.7–1.0   — auto-approve eligible
  1.0       — perfect track record with ≥ 10 tests
"""
from __future__ import annotations

import math
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_MIN_TESTS = 3
_NORMALIZER = math.log1p(10)   # log(11) ≈ 2.398
_AUTO_APPROVE_THRESHOLD = 0.70


def compute_trust_score(tests_completed: int, tests_positive: int) -> float:
    """
    Pure function: returns trust score in [0.0, 1.0].
    No DB access — can be used in tests without any fixtures.
    """
    if tests_completed < _MIN_TESTS or tests_completed == 0:
        return 0.0
    rate = tests_positive / tests_completed
    scale = math.log1p(tests_completed) / _NORMALIZER
    return min(rate * scale, 1.0)


def tests_needed_for_threshold(tests_completed: int, tests_positive: int) -> int:
    """
    Returns how many more *positive* tests are needed for trust_score ≥ 0.70.
    Returns 0 if already eligible, or a rough estimate.
    """
    if compute_trust_score(tests_completed, tests_positive) >= _AUTO_APPROVE_THRESHOLD:
        return 0
    # Simulate adding positive tests until threshold is met (max 50 iterations)
    needed = 0
    tc, tp = tests_completed, tests_positive
    for _ in range(50):
        tc += 1
        tp += 1
        needed += 1
        if compute_trust_score(tc, tp) >= _AUTO_APPROVE_THRESHOLD:
            break
    return needed


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def get_trust_score(
    db: AsyncSession,
    merchant_id: int,
    product_id: int,
) -> dict[str, Any]:
    """Return the current trust score record for a product."""
    result = await db.execute(
        text(
            """
            SELECT trust_score::float, tests_completed, tests_positive
            FROM product_trust_scores
            WHERE merchant_id = :merchant_id
              AND product_id = :product_id
            """
        ),
        {"merchant_id": merchant_id, "product_id": product_id},
    )
    row = result.mappings().first()
    if row is None:
        return {
            "trust_score": 0.0,
            "tests_completed": 0,
            "tests_positive": 0,
            "auto_approve_eligible": False,
            "tests_needed": _MIN_TESTS,
        }
    tc = int(row["tests_completed"])
    tp = int(row["tests_positive"])
    score = float(row["trust_score"])
    return {
        "trust_score": round(score, 4),
        "tests_completed": tc,
        "tests_positive": tp,
        "auto_approve_eligible": score >= _AUTO_APPROVE_THRESHOLD,
        "tests_needed": tests_needed_for_threshold(tc, tp),
    }


async def update_trust_score(
    db: AsyncSession,
    merchant_id: int,
    product_id: int,
    experiment_positive: bool,
    commit: bool = True,
) -> float:
    """
    Increment test counters then recompute and persist the trust score.
    Returns the new trust_score value.
    """
    result = await db.execute(
        text(
            """
            INSERT INTO product_trust_scores
              (merchant_id, product_id, tests_completed, tests_positive, trust_score)
            VALUES
              (:merchant_id, :product_id, 1, :pos, 0)
            ON CONFLICT (product_id, merchant_id) DO UPDATE
              SET tests_completed = product_trust_scores.tests_completed + 1,
                  tests_positive  = product_trust_scores.tests_positive  + :pos,
                  updated_at      = NOW()
            RETURNING tests_completed, tests_positive
            """
        ),
        {
            "merchant_id": merchant_id,
            "product_id": product_id,
            "pos": 1 if experiment_positive else 0,
        },
    )
    row = result.mappings().first()
    if row is None:
        return 0.0

    new_score = compute_trust_score(int(row["tests_completed"]), int(row["tests_positive"]))
    await db.execute(
        text(
            """
            UPDATE product_trust_scores
            SET trust_score = :score
            WHERE merchant_id = :merchant_id AND product_id = :product_id
            """
        ),
        {"merchant_id": merchant_id, "product_id": product_id, "score": new_score},
    )
    if commit:
        await db.commit()

    logger.info(
        "Trust score updated: merchant=%d product=%d score=%.4f (positive=%s)",
        merchant_id, product_id, new_score, experiment_positive,
    )
    return new_score
