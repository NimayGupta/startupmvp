"""
Phase 6C — Stripe Billing: Tier Enforcement Middleware

Tier limits
-----------
  free   : 1 product, 1 concurrent experiment, rules_v1 only
  growth : 20 products, 5 concurrent experiments, bandit_v1, weekly reports
  pro    : unlimited products, unlimited experiments, auto-approve, priority support

Any request that would exceed a limit receives HTTP 402 with an upgrade prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class TierLimits:
    max_products: int          # -1 = unlimited
    max_experiments: int       # -1 = unlimited
    bandit_allowed: bool
    auto_approve_allowed: bool


_LIMITS: dict[str, TierLimits] = {
    "free":   TierLimits(max_products=1,  max_experiments=1,  bandit_allowed=False, auto_approve_allowed=False),
    "growth": TierLimits(max_products=20, max_experiments=5,  bandit_allowed=True,  auto_approve_allowed=False),
    "pro":    TierLimits(max_products=-1, max_experiments=-1, bandit_allowed=True,  auto_approve_allowed=True),
}

_UPGRADE_URLS: dict[str, str] = {
    "free":   "https://apps.shopify.com/discount-optimizer/upgrade?plan=growth",
    "growth": "https://apps.shopify.com/discount-optimizer/upgrade?plan=pro",
    "pro":    "",
}


async def get_merchant_plan(db: AsyncSession, merchant_id: int) -> str:
    """Return the merchant's current plan slug (defaults to 'free')."""
    result = await db.execute(
        text(
            """
            SELECT plan FROM subscriptions
            WHERE merchant_id = :merchant_id
              AND status IN ('active', 'trialing')
            LIMIT 1
            """
        ),
        {"merchant_id": merchant_id},
    )
    row = result.mappings().first()
    return str(row["plan"]) if row else "free"


def _limits(plan: str) -> TierLimits:
    return _LIMITS.get(plan, _LIMITS["free"])


def _upgrade_error(plan: str, reason: str) -> HTTPException:
    next_plan = "growth" if plan == "free" else "pro"
    url = _UPGRADE_URLS.get(plan, "")
    detail: dict[str, Any] = {
        "error": "plan_limit_exceeded",
        "reason": reason,
        "current_plan": plan,
        "upgrade_to": next_plan,
    }
    if url:
        detail["upgrade_url"] = url
    return HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)


async def enforce_product_limit(
    db: AsyncSession,
    merchant_id: int,
) -> None:
    """Raise 402 if the merchant has reached their product limit."""
    plan = await get_merchant_plan(db, merchant_id)
    limits = _limits(plan)
    if limits.max_products == -1:
        return

    result = await db.execute(
        text("SELECT COUNT(*) FROM products WHERE merchant_id = :mid AND status = 'active'"),
        {"mid": merchant_id},
    )
    count = int(result.scalar() or 0)
    if count >= limits.max_products:
        raise _upgrade_error(
            plan,
            f"{plan.title()} plan allows {limits.max_products} product(s). "
            f"You have {count}. Upgrade to add more.",
        )


async def enforce_experiment_limit(
    db: AsyncSession,
    merchant_id: int,
) -> None:
    """Raise 402 if the merchant has reached their concurrent experiment limit."""
    plan = await get_merchant_plan(db, merchant_id)
    limits = _limits(plan)
    if limits.max_experiments == -1:
        return

    result = await db.execute(
        text(
            "SELECT COUNT(*) FROM experiments "
            "WHERE merchant_id = :mid AND status = 'active'"
        ),
        {"mid": merchant_id},
    )
    count = int(result.scalar() or 0)
    if count >= limits.max_experiments:
        raise _upgrade_error(
            plan,
            f"{plan.title()} plan allows {limits.max_experiments} concurrent experiment(s). "
            f"Upgrade to run more simultaneously.",
        )


async def enforce_bandit_access(
    db: AsyncSession,
    merchant_id: int,
) -> None:
    """Raise 402 if the merchant tries to use the bandit engine on a free plan."""
    plan = await get_merchant_plan(db, merchant_id)
    if not _limits(plan).bandit_allowed:
        raise _upgrade_error(
            plan,
            "The AI bandit engine (Thompson Sampling) requires the Growth plan or above.",
        )


async def enforce_auto_approve(
    db: AsyncSession,
    merchant_id: int,
) -> None:
    """Raise 402 if the merchant tries to enable auto-approve on a non-Pro plan."""
    plan = await get_merchant_plan(db, merchant_id)
    if not _limits(plan).auto_approve_allowed:
        raise _upgrade_error(
            plan,
            "Auto-approve requires the Pro plan.",
        )
