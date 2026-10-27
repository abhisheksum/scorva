import os
from celery import Celery
from apps.api.config import settings

celery_app = Celery(
    "scorva",
    broker=settings.REDIS_URL,
    include=["apps.api.workers.tasks", "apps.api.workers.reaper"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="evaluations.default",
    task_routes={
        "apps.api.workers.tasks.evaluate_submission": {"queue": "evaluations.default"},
        "apps.api.workers.reaper.reap_stalled_evaluation_jobs_task": {"queue": "evaluations.default"},
    },
    beat_schedule={
        "reap-stalled-evaluation-jobs": {
            "task": "apps.api.workers.reaper.reap_stalled_evaluation_jobs_task",
            "schedule": 15.0,  # Run reaper every 15 seconds
        },
    },
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

# Auto-register tasks
import apps.api.workers.tasks  # noqa: F401, E402
import apps.api.workers.reaper  # noqa: F401, E402
