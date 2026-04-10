"""
Celery application factory.

Broker:  Redis (db 1) — task queue
Backend: Redis (db 2) — result store

All Celery beat schedules are defined here so they are co-located with the
task registrations. Beat tasks run inside the worker process when started with
the --beat flag (dev) or as a separate celery beat process (production).
"""
import os

from celery import Celery
from celery.schedules import crontab

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "discount_optimizer",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=[
        "workers.tasks.sync",
        "workers.tasks.webhooks",
        "workers.tasks.feature_refresh",
    ],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Retry policy defaults (individual tasks can override)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result expiry
    result_expires=3600,
    # Beat schedule — periodic tasks
    beat_schedule={
        # Phase 2B: Refresh product feature vectors every 6 hours
        "feature-refresh": {
            "task": "workers.tasks.feature_refresh.refresh_all_merchants",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        # Phase 4D: Monitor active experiments every 6 hours
        "experiment-monitor": {
            "task": "workers.tasks.experiment_monitor.monitor_all_experiments",
            "schedule": crontab(minute=30, hour="*/6"),
        },
        # Phase 5C: Weekly model retraining (Sunday midnight UTC)
        "model-retrain": {
            "task": "workers.tasks.model_retrain.retrain_all_merchants",
            "schedule": crontab(minute=0, hour=0, day_of_week="sunday"),
        },
    },
)
