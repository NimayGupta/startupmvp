"""
Phase 5C — Weekly Model Retraining Celery Task

Runs every Sunday at midnight UTC (beat schedule defined in celery_app.py).

For each merchant on bandit_v1 (or on rules_v1 with >= 5 concluded experiments):
  - Calls POST /bandit/retrain/{merchant_id} on the engine
  - The engine replays 30 days of experiment outcomes and soft signals
  - Logs a single model_retrain_batch_completed event when done

Design: identical HTTP-delegate pattern to feature_refresh and experiment_monitor —
all heavy logic stays in the engine so this task stays thin and easily testable.
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
    name="workers.tasks.model_retrain.retrain_all_merchants",
    max_retries=2,
    default_retry_delay=600,      # 10 min
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,       # cap at 30 min
    retry_jitter=True,
)
def retrain_all_merchants(self: Any) -> dict[str, Any]:
    """
    Trigger bandit retraining for every merchant that has enough experiment history.
    """
    merchant_ids = _get_retrain_eligible_merchants()
    logger.info("Model retrain starting for %d merchants", len(merchant_ids))

    results: dict[str, Any] = {
        "total": len(merchant_ids),
        "success": 0,
        "failed": 0,
        "failed_ids": [],
        "promoted": [],
    }

    headers = {"Authorization": f"Bearer {INTERNAL_API_KEY}"}

    with httpx.Client(timeout=120) as client:
        for merchant_id in merchant_ids:
            try:
                resp = client.post(
                    f"{ENGINE_URL}/bandit/retrain/{merchant_id}",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                results["success"] += 1
                if data.get("promoted_to_bandit"):
                    results["promoted"].append(merchant_id)
                logger.info(
                    "Retrain OK for merchant %d: %d total observations, promoted=%s",
                    merchant_id,
                    data.get("total_observations", 0),
                    data.get("promoted_to_bandit", False),
                )
            except Exception as exc:
                logger.warning(
                    "Retrain failed for merchant_id=%s: %s", merchant_id, exc
                )
                results["failed"] += 1
                results["failed_ids"].append(merchant_id)

    _write_batch_event(merchant_ids, results)

    logger.info(
        "Model retrain complete: %d/%d successful, %d promoted to bandit_v1",
        results["success"],
        results["total"],
        len(results["promoted"]),
    )

    if results["failed"] > 0:
        raise RuntimeError(
            f"Model retrain had {results['failed']} failure(s): "
            f"merchant_ids={results['failed_ids']}"
        )

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_retrain_eligible_merchants() -> list[int]:
    """
    Returns merchants that should be retrained:
      - active_engine_version = 'bandit_v1'  (already promoted), OR
      - rules_v1 with >= 5 concluded experiments (promotion candidate)
    """
    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id
                FROM merchants m
                WHERE m.uninstalled_at IS NULL
                  AND (
                    m.active_engine_version = 'bandit_v1'
                    OR (
                      m.active_engine_version = 'rules_v1'
                      AND (
                        SELECT COUNT(*)
                        FROM experiments e
                        WHERE e.merchant_id = m.id
                          AND e.status IN ('concluded', 'killed')
                      ) >= 5
                    )
                  )
                ORDER BY m.id
                """
            )
            return [row["id"] for row in cur.fetchall()]


def _write_batch_event(
    merchant_ids: list[int],
    results: dict[str, Any],
) -> None:
    """Write one model_retrain_batch_completed event per merchant."""
    if not merchant_ids:
        return
    payload = json.dumps(results)
    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            for merchant_id in merchant_ids:
                cur.execute(
                    """
                    INSERT INTO event_log (merchant_id, event_type, payload)
                    VALUES (%s, 'model_retrain_batch_completed', %s)
                    """,
                    (merchant_id, payload),
                )
        conn.commit()
