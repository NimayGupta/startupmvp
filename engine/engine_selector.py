"""
Phase 5B — Engine Version Selector

Determines which recommendation engine to use for a given merchant:
  rules_v1  — deterministic rule-based engine (Phase 3A)
  bandit_v1 — Thompson Sampling contextual bandit (Phase 5A)

Selection logic
---------------
1. Read active_engine_version from the merchants table.
2. If rules_v1 and the merchant now has >= 5 concluded experiments,
   promote them to bandit_v1 (one-time, stored in DB).
3. If bandit_v1 but the bandit has no stored parameters yet (cold start
   for this context bucket), fall back to rules_v1 for this request only.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_PROMOTION_THRESHOLD = 5   # concluded experiments needed to switch to bandit_v1


async def get_engine_version(db: AsyncSession, merchant_id: int) -> str:
    """Return the merchant's current active_engine_version ('rules_v1' or 'bandit_v1')."""
    result = await db.execute(
        text("SELECT active_engine_version FROM merchants WHERE id = :id"),
        {"id": merchant_id},
    )
    row = result.mappings().first()
    return str(row["active_engine_version"]) if row else "rules_v1"


async def maybe_promote_to_bandit(
    db: AsyncSession,
    merchant_id: int,
    commit: bool = True,
) -> bool:
    """
    Promote merchant from rules_v1 to bandit_v1 if they have enough concluded
    experiments.  Returns True if a promotion happened.
    """
    result = await db.execute(
        text(
            """
            SELECT active_engine_version,
                   (SELECT COUNT(*)
                    FROM experiments
                    WHERE merchant_id = :mid
                      AND status IN ('concluded', 'killed')
                   ) AS concluded_count
            FROM merchants
            WHERE id = :mid
            """
        ),
        {"mid": merchant_id},
    )
    row = result.mappings().first()
    if row is None:
        return False
    if str(row["active_engine_version"]) == "bandit_v1":
        return False   # already promoted
    if int(row["concluded_count"]) < _PROMOTION_THRESHOLD:
        return False   # not enough experiments yet

    await db.execute(
        text(
            "UPDATE merchants SET active_engine_version = 'bandit_v1' WHERE id = :id"
        ),
        {"id": merchant_id},
    )
    if commit:
        await db.commit()
    logger.info(
        "Merchant %d promoted to bandit_v1 (%d concluded experiments)",
        merchant_id, int(row["concluded_count"]),
    )
    return True


async def has_bandit_params(
    db: AsyncSession,
    merchant_id: int,
    context_bucket: str,
) -> bool:
    """Return True if the DB contains any bandit parameters for this context."""
    result = await db.execute(
        text(
            """
            SELECT 1 FROM bandit_parameters
            WHERE merchant_id = :merchant_id
              AND context_bucket = :context_bucket
            LIMIT 1
            """
        ),
        {"merchant_id": merchant_id, "context_bucket": context_bucket},
    )
    return result.first() is not None


async def select_engine(
    db: AsyncSession,
    merchant_id: int,
    context_bucket: str,
) -> str:
    """
    Return the engine version to use for this recommendation request.
    Falls back to rules_v1 on cold start even if merchant is on bandit_v1.
    """
    version = await get_engine_version(db, merchant_id)
    if version == "bandit_v1":
        has_params = await has_bandit_params(db, merchant_id, context_bucket)
        if not has_params:
            logger.info(
                "Merchant %d: bandit_v1 cold start for context '%s', using rules_v1",
                merchant_id, context_bucket,
            )
            return "rules_v1"
    return version
