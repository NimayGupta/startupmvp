"""
Phase 4D — Experiment Monitor Celery Task

Runs every 6 hours (beat schedule in workers/celery_app.py).

For each active merchant, calls the engine's /experiments/monitor/{merchant_id}
endpoint which:
  1. Fetches aggregate order data for all active experiments.
  2. Computes Bayesian statistics (Gamma-Poisson model).
  3. Persists latest_stats to the experiments table.
  4. Auto-concludes experiments that hit the significance or kill-switch threshold.
  5. Logs all decisions to event_log.

The worker deliberately does not run PyMC directly — it delegates all heavy
statistical computation to the engine container, which has PyMC installed.
"""
from __future__ import annotations

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
    name="workers.tasks.experiment_monitor.monitor_all_experiments",
    max_retries=3,
    default_retry_delay=300,       # 5 min
    autoretry_for=(Exception,),
    retry_backoff=True,            # exponential: 5m → 10m → 20m
    retry_backoff_max=1200,        # cap at 20 min
    retry_jitter=True,
)
def monitor_all_experiments(self: Any) -> dict[str, Any]:
    """
    Refresh Bayesian stats and auto-conclude experiments for all active merchants.
    Raises RuntimeError on partial failures so Celery retries the task.
    """
    merchant_ids = _get_active_merchant_ids()
    logger.info("Experiment monitor starting for %d merchants", len(merchant_ids))

    results: dict[str, Any] = {
        "total": len(merchant_ids),
        "success": 0,
        "failed": 0,
        "failed_ids": [],
        "concluded": 0,
        "kill_switched": 0,
    }

    headers = {"Authorization": f"Bearer {INTERNAL_API_KEY}"}

    with httpx.Client(timeout=120) as client:
        for merchant_id in merchant_ids:
            try:
                resp = client.post(
                    f"{ENGINE_URL}/experiments/monitor/{merchant_id}",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                results["success"] += 1
                results["concluded"] += data.get("concluded", 0)
                results["kill_switched"] += data.get("kill_switched", 0)
                logger.info(
                    "merchant_id=%d: monitored=%d concluded=%d kill_switched=%d",
                    merchant_id,
                    data.get("monitored", 0),
                    data.get("concluded", 0),
                    data.get("kill_switched", 0),
                )
            except Exception as exc:
                logger.exception("Experiment monitor failed for merchant_id=%d: %s", merchant_id, exc)
                results["failed"] += 1
                results["failed_ids"].append(merchant_id)

    _write_monitor_event(results)

    if results["failed"] > 0:
        raise RuntimeError(
            f"Experiment monitor failed for {results['failed']} merchants: {results['failed_ids']}"
        )

    logger.info(
        "Experiment monitor complete: %d success, %d concluded, %d kill_switched",
        results["success"],
        results["concluded"],
        results["kill_switched"],
    )
    return results


def _get_active_merchant_ids() -> list[int]:
    """Return IDs of all merchants with at least one active experiment."""
    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT merchant_id
                FROM experiments
                WHERE status = 'active'
                ORDER BY merchant_id
                """
            )
            return [row["merchant_id"] for row in cur.fetchall()]


def _write_monitor_event(results: dict[str, Any]) -> None:
    """Write a summary event to event_log for observability."""
    import json

    with get_sync_db_connection() as conn:
        with conn.cursor() as cur:
            for merchant_id in _get_active_merchant_ids():
                cur.execute(
                    """
                    INSERT INTO event_log (merchant_id, event_type, payload)
                    VALUES (%s, 'experiment_monitor_completed', %s)
                    """,
                    (merchant_id, json.dumps(results)),
                )
        conn.commit()
