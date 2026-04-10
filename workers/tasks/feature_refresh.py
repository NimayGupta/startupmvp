"""
Phase 2B — Feature Refresh Celery Task

Runs every 6 hours (Celery Beat schedule defined in celery_app.py).
For each active merchant, calls the FastAPI engine's /features endpoint
with ?refresh=true to recompute and cache feature vectors.

Design note: The Celery worker is synchronous. Rather than duplicating the
async SQLAlchemy feature computation here, we call the engine via HTTP.
This keeps all feature logic in one place (engine/features/compute.py).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from celery.utils.log import get_task_logger

from workers.celery_app import celery_app
from workers.db import get_sync_db_connection

logger = get_task_logger(__name__)

ENGINE_URL = os.getenv("ENGINE_URL", "http://localhost:8000")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


@celery_app.task(
    bind=True,
    name="workers.tasks.feature_refresh.refresh_all_merchants",
    max_retries=3,
    default_retry_delay=300,       # 5 min
    autoretry_for=(Exception,),
    retry_backoff=True,            # exponential: 5m → 10m → 20m
    retry_backoff_max=1200,        # cap at 20 min
    retry_jitter=True,
)
def refresh_all_merchants(self: Any) -> dict[str, Any]:
    """
    Refresh feature vectors for all active merchants.
    Raises RuntimeError on partial failures so Celery retries the task.
    """
    merchant_ids = _get_active_merchant_ids()
    logger.info("Feature refresh starting for %d merchants", len(merchant_ids))

    results: dict[str, Any] = {
        "total": len(merchant_ids),
        "success": 0,
        "failed": 0,
        "failed_ids": [],
    }

    headers = {"Authorization": f"Bearer {INTERNAL_API_KEY}"}

    with httpx.Client(timeout=60) as client:
        for merchant_id in merchant_ids:
            try:
                resp = client.get(
                    f"{ENGINE_URL}/features/{merchant_id}",
                    params={"refresh": "true"},
                    headers=headers,
                )
                resp.raise_for_status()
                results["success"] += 1
            except Exception as exc:
                logger.warning(
                    "Feature refresh failed for merchant_id=%s: %s",
                    merchant_id,
                    exc,
                )
                results["failed"] += 1
                results["failed_ids"].append(merchant_id)

    _write_refresh_events(merchant_ids, results)

    logger.info(
        "Feature refresh complete: %d/%d successful",
        results["success"],
        results["total"],
    )

    if results["failed"] > 0:
        raise RuntimeError(
            f"Feature refresh had {results['failed']} failure(s): "
            f"merchant_ids={results['failed_ids']}"
        )

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_merchant_ids() -> list[int]:
    """Returns IDs of all installed (non-uninstalled) merchants."""
    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM merchants WHERE uninstalled_at IS NULL ORDER BY id"
            )
            return [row["id"] for row in cur.fetchall()]


def _write_refresh_events(
    merchant_ids: list[int], results: dict[str, Any]
) -> None:
    """Appends one feature_refresh_completed event per merchant to event_log."""
    if not merchant_ids:
        return

    payload = json.dumps(results)
    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            for merchant_id in merchant_ids:
                cur.execute(
                    """
                    INSERT INTO event_log (merchant_id, event_type, payload)
                    VALUES (%s, 'feature_refresh_completed', %s)
                    """,
                    (merchant_id, payload),
                )
        conn.commit()
