import logging
import os
from typing import Any, Dict
import uuid

from apps.api.workers.celery_app import celery_app
from apps.api.workers.pipeline import PipelineResult, run_evaluation_pipeline

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="apps.api.workers.tasks.evaluate_submission",
    max_retries=0,  # Retries are governed by orchestrator/reaper, not blind Celery auto-retries
    acks_late=True,
    reject_on_worker_lost=True,
)
def evaluate_submission(self, job_id: str) -> Dict[str, Any]:
    """
    Subsystem C Sub-Milestones 5.2 & 5.3: Evaluation Task Consumer & Pipeline Entrypoint.
    
    Invariants:
    1. Minimal payload: Accepts only the stable job_id string. Zero repository contents
       or secrets in broker message.
    2. Short-lived DB claim: Atomically transitions 'queued' -> 'running' with server-time lease.
    3. Duplicate delivery harmless: Non-claimable jobs return discarded status without side-effects.
    4. End-to-end evaluation pipeline: Compiles prompt, executes inference, validates scores,
       and atomically persists results under PostgreSQL pessimistic row lock.
    5. Fencing & Atomicity: Stale workers cannot commit; results are never partially committed.
    """
    try:
        parsed_job_id = uuid.UUID(job_id)
    except (ValueError, TypeError):
        logger.error("Invalid job_id format in Celery payload: %s", job_id)
        return {"status": "error", "error": "INVALID_JOB_ID", "job_id": job_id}

    worker_id = getattr(self.request, "hostname", None) or f"worker-{os.getpid()}"

    pipeline_res: PipelineResult = run_evaluation_pipeline(
        job_id=parsed_job_id,
        worker_id=worker_id,
    )

    return {
        "status": pipeline_res.status,
        "job_id": str(pipeline_res.job_id),
        "result_id": str(pipeline_res.result_id) if pipeline_res.result_id else None,
        "lock_version": pipeline_res.lock_version,
        "raw_score": str(pipeline_res.raw_score) if pipeline_res.raw_score is not None else None,
        "normalized_score": str(pipeline_res.normalized_score) if pipeline_res.normalized_score is not None else None,
        "error_code": pipeline_res.error_code,
        "error_message": pipeline_res.error_message,
        "reason": pipeline_res.error_code,
        "attempts_count": 1,
    }
