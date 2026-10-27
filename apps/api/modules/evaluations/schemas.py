from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field
from apps.api.modules.evaluations.scoring_calculator import ScoringMode
from apps.api.modules.evaluations.output_validator import (
    AICriterionScorePayload,
    AIEvaluationOutputPayload,
    AIEvidenceReferencePayload,
)


class RubricCriterionBase(BaseModel):
    title: str = Field(..., max_length=150)
    description: str
    weight: Decimal = Field(..., gt=0, le=1)
    min_score: Decimal = Field(default=Decimal("0.00"))
    max_score: Decimal = Field(default=Decimal("10.00"))
    evidence_requirements: str
    order_index: int = 0


class RubricCriterionCreate(RubricCriterionBase):
    pass


class RubricCriterionResponse(RubricCriterionBase):
    id: uuid.UUID
    rubric_version_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class RubricVersionResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    rubric_id: uuid.UUID
    version_number: int
    status: str
    published_at: Optional[datetime]
    created_at: datetime
    criteria: List[RubricCriterionResponse] = []

    model_config = ConfigDict(from_attributes=True)


class RubricCreate(BaseModel):
    name: str = Field(..., max_length=150)
    description: Optional[str] = None
    scoring_mode: ScoringMode = ScoringMode.OFFSET_NORMALIZED


class RubricResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    name: str
    description: Optional[str]
    scoring_mode: str
    created_at: datetime
    updated_at: datetime
    versions: List[RubricVersionResponse] = []

    model_config = ConfigDict(from_attributes=True)


class TeamMemberResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID
    role_in_team: str
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TeamCreate(BaseModel):
    name: str = Field(..., max_length=150)


class TeamResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    name: str
    join_code: str
    created_by_user_id: uuid.UUID
    created_at: datetime
    members: List[TeamMemberResponse] = []

    model_config = ConfigDict(from_attributes=True)


class SubmissionCreate(BaseModel):
    team_id: uuid.UUID
    repository_url: str = Field(..., max_length=500)
    target_branch: str = Field(default="main", max_length=100)
    title: str = Field(..., max_length=200)
    description: Optional[str] = None


class SubmissionResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    team_id: uuid.UUID
    team_name: str
    repository_url: str
    target_branch: str
    title: str
    description: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SubmissionSnapshotResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    submission_id: uuid.UUID
    commit_sha: str
    tree_sha: Optional[str]
    snapshot_tarball_url: Optional[str]
    file_count: int
    total_bytes: int
    configuration_snapshot: Dict[str, Any]
    metadata_: Dict[str, Any] = Field(..., alias="metadata")
    captured_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class EvaluationJobResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    submission_id: uuid.UUID
    snapshot_id: uuid.UUID
    rubric_version_id: uuid.UUID
    status: str
    current_stage: Optional[str] = None
    attempts_count: int
    max_attempts: int
    lock_version: int
    idempotency_key: Optional[str] = None
    request_fingerprint: Optional[str] = None
    dispatch_generation: int
    reevaluation_of_job_id: Optional[uuid.UUID] = None
    cancellation_requested: bool
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class EvaluationJobDispatchResponse(BaseModel):
    job: EvaluationJobResponse
    is_created: bool


class EvaluationJobCreateRequest(BaseModel):
    submission_id: uuid.UUID
    snapshot_id: uuid.UUID
    rubric_version_id: uuid.UUID
    configuration_override: Optional[Dict[str, Any]] = None


class EvaluationReevaluateRequest(BaseModel):
    rubric_version_id: Optional[uuid.UUID] = None
    configuration_override: Optional[Dict[str, Any]] = None


class EvaluationOutboxResponse(BaseModel):
    id: int
    job_id: uuid.UUID
    organization_id: uuid.UUID
    queue_name: str
    status: str
    claim_count: int
    publish_attempts: int
    dispatch_generation: int
    last_error: Optional[str] = None
    dead_letter_reason: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Subsystem C Sub-Milestone 6.4: AI Evaluation Transparency Schemas
# ==============================================================================

SAFE_ERROR_DESCRIPTIONS: Dict[str, str] = {
    "PROVIDER_RATE_LIMIT": "AI evaluation provider rate limit encountered. Job will be retried automatically.",
    "PROVIDER_TIMEOUT": "AI evaluation request timed out while assessing repository evidence.",
    "PROVIDER_UNAVAILABLE": "AI evaluation service is temporarily unavailable. Job will be retried.",
    "ACQUISITION_TIMEOUT": "Repository download or clone timed out.",
    "ACQUISITION_FAILED": "Repository could not be cloned or accessed.",
    "EXTRACTION_FAILED": "Failed to extract repository snapshot contents safely.",
    "EVIDENCE_INDEXING_FAILED": "Evidence extraction or indexing failed for this repository snapshot.",
    "OUTPUT_VALIDATION_FAILED": "Model assessment did not pass strict schema validation.",
    "LEASE_EXPIRED": "Worker lease expired during processing. Recovered by scheduler.",
    "WORKER_CRASHED": "Worker terminated unexpectedly during processing.",
    "SUBMISSION_CANCELLED": "Evaluation was cancelled by an organizer before completion.",
    "INTERNAL_ERROR": "An unexpected error occurred during evaluation.",
    "UNKNOWN_ERROR": "Evaluation encountered an unclassified error. Organizers can retry.",
}


def sanitize_error_for_display(
    error_code: Optional[str],
    raw_error_message: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Sanitizes internal error codes and diagnostic messages for safe judge/organizer display.
    Never exposes internal credentials, file system paths, or raw stack traces.
    """
    if not error_code and not raw_error_message:
        return None, None

    code = (error_code or "UNKNOWN_ERROR").upper()
    safe_desc = SAFE_ERROR_DESCRIPTIONS.get(code)
    if not safe_desc:
        safe_desc = "Evaluation encountered an unclassified error. Organizers can retry."

    return code, safe_desc


class EvidenceReferenceDetail(BaseModel):
    id: uuid.UUID
    file_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    snippet: str
    is_verified_in_repo: bool = True
    verification_failure_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CriterionScoreDetail(BaseModel):
    id: uuid.UUID
    criterion_id: uuid.UUID
    title: str
    description: str
    weight: Decimal
    min_score: Decimal
    max_score: Decimal
    order_index: int
    awarded_score: Decimal
    normalized_criterion_score: Decimal
    confidence_score: Decimal
    rationale: str
    evidence_status: str
    evidence_references: List[EvidenceReferenceDetail] = []

    model_config = ConfigDict(from_attributes=True)


class EvaluationResultDetail(BaseModel):
    id: uuid.UUID
    attempt_number: int
    model_provider: str
    model_name: str
    prompt_version: str
    raw_score: Decimal
    normalized_score: Decimal
    summary_assessment: str
    has_insufficient_evidence: bool
    created_at: datetime
    criterion_scores: List[CriterionScoreDetail] = []

    model_config = ConfigDict(from_attributes=True)


class EvaluationJobSummary(BaseModel):
    id: uuid.UUID
    status: str
    current_stage: Optional[str] = None
    attempts_count: int
    max_attempts: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    is_retryable: bool = False
    cancellation_requested: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvaluationRubricSummary(BaseModel):
    rubric_id: uuid.UUID
    rubric_name: str
    rubric_version_id: uuid.UUID
    version_number: int
    scoring_mode: str

    model_config = ConfigDict(from_attributes=True)


class EvaluationSnapshotSummary(BaseModel):
    snapshot_id: uuid.UUID
    commit_sha: str
    file_count: int
    total_bytes: int
    captured_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PriorEvaluationRunSummary(BaseModel):
    job_id: uuid.UUID
    status: str
    attempts_count: int
    raw_score: Optional[Decimal] = None
    normalized_score: Optional[Decimal] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubmissionEvaluationTransparencyResponse(BaseModel):
    submission_id: uuid.UUID
    submission_title: str
    team_name: str
    repository_url: str
    target_branch: str
    verified_commit_sha: Optional[str] = None
    can_evaluate: bool
    cannot_evaluate_reason: Optional[str] = None
    has_evaluation: bool
    job: Optional[EvaluationJobSummary] = None
    rubric: Optional[EvaluationRubricSummary] = None
    snapshot: Optional[EvaluationSnapshotSummary] = None
    result: Optional[EvaluationResultDetail] = None
    prior_runs: List[PriorEvaluationRunSummary] = []

    model_config = ConfigDict(from_attributes=True)


class HackathonEvaluationSummaryResponse(BaseModel):
    total_submissions: int
    evaluated_submissions: int
    queued_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    average_score: Optional[Decimal] = None
    has_published_rubric: bool
    published_rubric_id: Optional[uuid.UUID] = None
    published_rubric_version_id: Optional[uuid.UUID] = None
    published_rubric_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EvaluationJobListItem(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    submission_title: str
    team_name: str
    status: str
    current_stage: Optional[str] = None
    attempts_count: int
    max_attempts: int
    raw_score: Optional[Decimal] = None
    normalized_score: Optional[Decimal] = None
    error_code: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TriggerEvaluationRequest(BaseModel):
    configuration_override: Optional[Dict[str, Any]] = None


# ==============================================================================
# Subsystem C Sub-Milestone 6.5: Judge Review & Independent Human Decisions
# ==============================================================================

class JudgeCriterionScoreInput(BaseModel):
    criterion_id: uuid.UUID
    score: Decimal = Field(..., ge=0, description="Criterion score awarded by the human judge")
    judge_notes: Optional[str] = Field(None, max_length=5000, description="Optional criterion-level feedback or rationale")


class SaveJudgeReviewRequest(BaseModel):
    overall_feedback: Optional[str] = Field(None, max_length=10000, description="Overall review feedback")
    decision: Optional[str] = Field(None, description="Judge decision: 'accepted', 'adjusted', or 'rejected'")
    criterion_scores: List[JudgeCriterionScoreInput] = Field(default_factory=list)
    version: Optional[int] = Field(None, description="Optimistic concurrency control version")


class SubmitJudgeReviewRequest(BaseModel):
    overall_feedback: str = Field(..., min_length=1, max_length=10000, description="Mandatory overall review feedback")
    decision: Optional[str] = Field("accepted", description="Judge decision: 'accepted', 'adjusted', or 'rejected'")
    criterion_scores: List[JudgeCriterionScoreInput] = Field(..., min_length=1, description="Scores for all published criteria")
    version: Optional[int] = Field(None, description="Optimistic concurrency control version")


class JudgeCriterionScoreDetail(BaseModel):
    id: Optional[uuid.UUID] = None
    criterion_id: uuid.UUID
    criterion_title: str
    weight: Decimal
    min_score: Decimal
    max_score: Decimal
    score: Optional[Decimal] = None
    judge_notes: Optional[str] = None
    ai_suggested_score: Optional[Decimal] = None
    ai_rationale: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class JudgeReviewDetail(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    hackathon_id: uuid.UUID
    submission_id: uuid.UUID
    rubric_version_id: uuid.UUID
    judge_user_id: uuid.UUID
    judge_name: Optional[str] = None
    judge_email: Optional[str] = None
    status: str
    score: Optional[Decimal] = None
    overall_feedback: Optional[str] = None
    decision: Optional[str] = None
    version: int
    created_at: datetime
    updated_at: datetime
    submitted_at: Optional[datetime] = None
    criterion_scores: List[JudgeCriterionScoreDetail] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class JudgeSubmissionReviewResponse(BaseModel):
    submission_id: uuid.UUID
    hackathon_id: uuid.UUID
    organization_id: uuid.UUID
    team_name: str
    submission_title: str
    repository_url: str
    repository_owner: Optional[str] = None
    repository_name: Optional[str] = None
    target_branch: str
    verified_commit_sha: Optional[str] = None
    connection_status: str
    rubric_id: uuid.UUID
    rubric_version_id: uuid.UUID
    rubric_name: str
    rubric_criteria: List[Dict[str, Any]] = Field(default_factory=list)
    ai_evaluation: Optional[EvaluationResultDetail] = None
    review: Optional[JudgeReviewDetail] = None
    can_edit: bool

    model_config = ConfigDict(from_attributes=True)


class JudgeQueueItem(BaseModel):
    submission_id: uuid.UUID
    team_name: str
    title: str
    repository_owner: Optional[str] = None
    repository_name: Optional[str] = None
    target_branch: str
    verified_commit_sha: Optional[str] = None
    connection_status: str
    ai_evaluation_status: str
    ai_normalized_score: Optional[Decimal] = None
    review_status: str
    review_score: Optional[Decimal] = None
    review_submitted_at: Optional[datetime] = None
    review_updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class JudgeAssignmentItem(BaseModel):
    hackathon_id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    hackathon_title: str
    hackathon_slug: str
    hackathon_status: str
    submission_deadline: Optional[datetime] = None
    end_date: Optional[datetime] = None
    assigned_at: datetime
    total_submissions: int
    my_draft_count: int
    my_submitted_count: int
    my_pending_count: int

    model_config = ConfigDict(from_attributes=True)


class JudgeHackathonDetailResponse(BaseModel):
    hackathon_id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    hackathon_title: str
    hackathon_slug: str
    hackathon_status: str
    description: Optional[str] = None
    submission_deadline: Optional[datetime] = None
    end_date: Optional[datetime] = None
    total_submissions: int = 0
    my_draft_count: int = 0
    my_submitted_count: int = 0
    my_pending_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class JudgeProgressItem(BaseModel):
    judge_user_id: uuid.UUID
    judge_name: Optional[str] = None
    judge_email: str
    assigned_at: datetime
    submitted_count: int
    draft_count: int
    pending_count: int

    model_config = ConfigDict(from_attributes=True)


class SubmissionCoverageItem(BaseModel):
    submission_id: uuid.UUID
    team_name: str
    title: str
    submitted_reviews_count: int
    draft_reviews_count: int
    average_human_score: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class OrganizerReviewProgressResponse(BaseModel):
    total_submissions: int
    total_judges: int
    submissions_with_reviews: int
    submissions_fully_reviewed: int
    submissions_awaiting_review: int
    draft_reviews_count: int
    submitted_reviews_count: int
    judge_progress: List[JudgeProgressItem] = Field(default_factory=list)
    submission_coverage: List[SubmissionCoverageItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SubmissionReviewsResponse(BaseModel):
    submission_id: uuid.UUID
    reviews: List[JudgeReviewDetail] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


