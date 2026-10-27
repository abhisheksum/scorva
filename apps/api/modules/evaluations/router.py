from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.database import get_db_session
from apps.api.core.exceptions import AppException
from apps.api.dependencies import (
    OrgRole,
    TenantContext,
    require_org_admin,
    require_org_member,
    require_org_role,
)
from apps.api.modules.evaluations.models import EvaluationJob
from apps.api.modules.evaluations.outbox import (
    get_outbox_entries_for_job,
    get_outbox_entry_by_id,
    replay_dead_lettered_outbox_row,
)
from apps.api.modules.evaluations.schemas import (
    EvaluationJobCreateRequest,
    EvaluationJobResponse,
    EvaluationOutboxResponse,
    EvaluationReevaluateRequest,
)
from apps.api.modules.evaluations.service import (
    cancel_evaluation_job_atomic,
    dispatch_evaluation_job_atomic,
    reevaluate_submission_atomic,
)

router = APIRouter(prefix="/organizations/{org_id}", tags=["Evaluations"])

require_evaluator = require_org_role(
    OrgRole.ORG_OWNER,
    OrgRole.ORG_ADMIN,
    OrgRole.ORGANIZER,
)


def _extract_telemetry(request: Request):
    ip_address = getattr(
        request.state,
        "client_ip",
        request.client.host if request.client else "127.0.0.1",
    )
    user_agent = request.headers.get("user-agent", "Unknown")
    correlation_id = getattr(request.state, "correlation_id", None)
    return ip_address, user_agent, correlation_id


@router.post(
    "/hackathons/{hackathon_id}/evaluations",
    response_model=EvaluationJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def dispatch_evaluation(
    hackathon_id: uuid.UUID,
    payload: EvaluationJobCreateRequest,
    request: Request,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 5.1:
    Atomically creates an EvaluationJob, its EvaluationJobOutbox record, and the corresponding AuditEvent.
    Returns 201 Created on fresh dispatch, or 200 OK with header Idempotent-Replay: true on idempotent retry.
    """
    ip_address, user_agent, correlation_id = _extract_telemetry(request)

    job, is_created = await dispatch_evaluation_job_atomic(
        db=db,
        organization_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=payload.submission_id,
        snapshot_id=payload.snapshot_id,
        rubric_version_id=payload.rubric_version_id,
        idempotency_key=idempotency_key,
        configuration_override=payload.configuration_override,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    if not is_created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replay"] = "true"

    return job


@router.post(
    "/hackathons/{hackathon_id}/submissions/{submission_id}/reevaluate",
    response_model=EvaluationJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reevaluate_submission(
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: EvaluationReevaluateRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 5.1:
    Explicit Intentional Re-Evaluation:
    Dispatches a fresh evaluation job while preserving historical runs and results.
    """
    ip_address, user_agent, correlation_id = _extract_telemetry(request)

    # Resolve snapshot_id from latest submission snapshot if not provided
    from apps.api.modules.evaluations.models import SubmissionSnapshot

    stmt_snap = (
        select(SubmissionSnapshot)
        .where(
            SubmissionSnapshot.submission_id == submission_id,
            SubmissionSnapshot.organization_id == tenant.organization.id,
        )
        .order_by(SubmissionSnapshot.captured_at.desc())
    )
    latest_snap = (await db.execute(stmt_snap)).scalars().first()
    if not latest_snap:
        raise AppException(
            status_code=404,
            code="SNAPSHOT_NOT_FOUND",
            message="No snapshots found for this submission.",
        )

    # Resolve rubric_version_id
    rubric_version_id = payload.rubric_version_id
    if not rubric_version_id:
        from apps.api.modules.evaluations.models import EvaluationJob

        stmt_prev = (
            select(EvaluationJob.rubric_version_id)
            .where(
                EvaluationJob.submission_id == submission_id,
                EvaluationJob.organization_id == tenant.organization.id,
            )
            .order_by(EvaluationJob.created_at.desc())
        )
        rubric_version_id = (await db.execute(stmt_prev)).scalar_one_or_none()
        if not rubric_version_id:
            raise AppException(
                status_code=400,
                code="RUBRIC_VERSION_REQUIRED",
                message="rubric_version_id must be provided or resolvable from previous evaluation.",
            )

    job, _ = await reevaluate_submission_atomic(
        db=db,
        organization_id=tenant.organization.id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        snapshot_id=latest_snap.id,
        rubric_version_id=rubric_version_id,
        idempotency_key=idempotency_key,
        configuration_override=payload.configuration_override,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )

    return job


@router.get(
    "/evaluations/{job_id}",
    response_model=EvaluationJobResponse,
)
async def get_evaluation_job(
    job_id: uuid.UUID,
    tenant: TenantContext = Depends(require_org_member),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves an evaluation job by ID strictly within the caller's organization."""
    stmt = (
        select(EvaluationJob)
        .where(
            EvaluationJob.id == job_id,
            EvaluationJob.organization_id == tenant.organization.id,
        )
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise AppException(
            status_code=404,
            code="EVALUATION_JOB_NOT_FOUND",
            message="Evaluation job not found in this organization.",
        )
    return job


@router.get(
    "/evaluations/{job_id}/outbox",
    response_model=List[EvaluationOutboxResponse],
)
async def get_job_outbox_entries(
    job_id: uuid.UUID,
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieves outbox dispatch records for an evaluation job."""
    return await get_outbox_entries_for_job(
        db=db,
        job_id=job_id,
        organization_id=tenant.organization.id,
    )


@router.post(
    "/evaluations/outbox/{outbox_id}/replay",
    response_model=EvaluationOutboxResponse,
)
async def replay_outbox_entry(
    outbox_id: int,
    tenant: TenantContext = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Authorized Operator Replay:
    Resets a dead-lettered outbox entry to pending status and emits an audit event.
    """
    row = await replay_dead_lettered_outbox_row(
        db=db,
        organization_id=tenant.organization.id,
        outbox_id=outbox_id,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
    )
    return row


@router.post(
    "/evaluations/{job_id}/cancel",
    response_model=EvaluationJobResponse,
)
async def cancel_evaluation(
    job_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(require_evaluator),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Subsystem C Sub-Milestone 5.4: Cooperative Evaluation Cancellation Endpoint.
    - If queued: immediately marks cancelled and dead-letters pending outbox entries.
    - If running: sets cancellation_requested flag for cooperative worker abort.
    - If already completed: returns 409 Conflict (CANNOT_CANCEL_COMPLETED).
    - If already cancelled or failed: returns current state (idempotent).
    """
    ip_address, user_agent, correlation_id = _extract_telemetry(request)
    await cancel_evaluation_job_atomic(
        db=db,
        job_id=job_id,
        organization_id=tenant.organization.id,
        actor_user_id=tenant.user.id,
        actor_email=tenant.user.email,
        actor_role=tenant.membership.role.value,
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )
    job = (
        await db.execute(
            select(EvaluationJob).where(
                EvaluationJob.id == job_id,
                EvaluationJob.organization_id == tenant.organization.id,
            )
        )
    ).scalar_one_or_none()
    return job
