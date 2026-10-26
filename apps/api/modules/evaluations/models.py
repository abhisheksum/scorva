from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from apps.api.core.database import Base

if TYPE_CHECKING:
    from apps.api.modules.organizations.models import Organization
    from apps.api.modules.hackathons.models import Hackathon
    from apps.api.modules.users.models import User


class Team(Base):
    """Subsystem C: Participant teams registered within a hackathon."""
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    hackathon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hackathons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    join_code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("hackathon_id", "name", name="uq_teams_hackathon_name"),
    )

    members: Mapped[List["TeamMember"]] = relationship(
        "TeamMember", back_populates="team", cascade="all, delete-orphan"
    )
    submissions: Mapped[List["Submission"]] = relationship(
        "Submission", back_populates="team"
    )


class TeamMember(Base):
    """Subsystem C: Association linking individual participants to a team."""
    __tablename__ = "team_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_in_team: Mapped[str] = mapped_column(
        String(20), nullable=False, default="member"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
        CheckConstraint(
            "role_in_team IN ('leader', 'member')",
            name="chk_team_members_role",
        ),
    )

    team: Mapped["Team"] = relationship("Team", back_populates="members")


class Submission(Base):
    """Subsystem C: Project submissions submitted to a hackathon by participating teams."""
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    hackathon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hackathons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    team_name: Mapped[str] = mapped_column(String(150), nullable=False)
    repository_url: Mapped[str] = mapped_column(String(500), nullable=False)
    target_branch: Mapped[str] = mapped_column(
        String(100), nullable=False, default="main"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'evaluated', 'flagged', 'withdrawn')",
            name="chk_submissions_status",
        ),
        Index(
            "uq_submissions_hackathon_repo_active",
            "hackathon_id",
            "repository_url",
            unique=True,
            postgresql_where=(deleted_at.is_(None)),
        ),
        Index("idx_submissions_hackathon_status", "hackathon_id", "status"),
        Index("idx_submissions_team", "team_id"),
    )

    team: Mapped["Team"] = relationship("Team", back_populates="submissions")
    snapshots: Mapped[List["SubmissionSnapshot"]] = relationship(
        "SubmissionSnapshot", back_populates="submission"
    )
    evaluation_jobs: Mapped[List["EvaluationJob"]] = relationship(
        "EvaluationJob", back_populates="submission"
    )


class SubmissionSnapshot(Base):
    """
    Subsystem C: Represents an immutable frozen commit SHA captured at evaluation time.
    Evaluations are permanently bound to a snapshot and its effective configuration.
    """
    __tablename__ = "submission_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("submissions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    tree_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    snapshot_tarball_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    configuration_snapshot: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False
    )
    metadata_: Mapped[Dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "submission_id", "commit_sha", name="uq_submission_snapshots_submission_commit"
        ),
    )

    submission: Mapped["Submission"] = relationship(
        "Submission", back_populates="snapshots"
    )
    evaluation_jobs: Mapped[List["EvaluationJob"]] = relationship(
        "EvaluationJob", back_populates="snapshot"
    )


class Rubric(Base):
    """Subsystem C: Parent rubric configuration for a hackathon."""
    __tablename__ = "rubrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    hackathon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hackathons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scoring_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="offset_normalized"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("hackathon_id", "name", name="uq_rubrics_hackathon_name"),
        CheckConstraint(
            "scoring_mode IN ('offset_normalized', 'raw_proportional')",
            name="chk_rubrics_scoring_mode",
        ),
    )

    versions: Mapped[List["RubricVersion"]] = relationship(
        "RubricVersion", back_populates="rubric", cascade="all, delete-orphan"
    )


class RubricVersion(Base):
    """Subsystem C: Immutable frozen snapshot of criteria and weights used for evaluation runs."""
    __tablename__ = "rubric_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rubric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rubrics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "rubric_id", "version_number", name="uq_rubric_versions_rubric_version"
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="chk_rubric_versions_status",
        ),
    )

    rubric: Mapped["Rubric"] = relationship("Rubric", back_populates="versions")
    criteria: Mapped[List["RubricCriterion"]] = relationship(
        "RubricCriterion",
        back_populates="rubric_version",
        cascade="all, delete-orphan",
        order_by="RubricCriterion.order_index",
    )


class RubricCriterion(Base):
    """
    Subsystem C: Individual assessment criterion belonging to a rubric version.
    Protected by PostgreSQL immutability trigger once rubric_version is published.
    """
    __tablename__ = "rubric_criteria"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rubric_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    min_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00")
    )
    max_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("10.00")
    )
    evidence_requirements: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("min_score < max_score", name="chk_rubric_criteria_min_max"),
        CheckConstraint(
            "weight > 0.0000 AND weight <= 1.0000",
            name="chk_rubric_criteria_weight",
        ),
    )

    rubric_version: Mapped["RubricVersion"] = relationship(
        "RubricVersion", back_populates="criteria"
    )


class EvaluationJob(Base):
    """Subsystem C: Asynchronous job tracking evaluation orchestration and worker leasing."""
    __tablename__ = "evaluation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    hackathon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hackathons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("submissions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("submission_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rubric_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    current_result_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "evaluation_results.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_evaluation_jobs_current_result_id",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued"
    )
    current_stage: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    attempts_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    claim_token: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_evaluation_jobs_status",
        ),
        CheckConstraint(
            "current_stage IS NULL OR current_stage IN ("
            "'repo_acquisition', 'safe_extraction', 'evidence_indexing', "
            "'model_evaluation', 'output_validation', 'score_calculation', 'persistence')",
            name="chk_evaluation_jobs_current_stage",
        ),
        Index("idx_eval_jobs_status_heartbeat", "status", "last_heartbeat_at"),
        Index("idx_eval_jobs_org_hack", "organization_id", "hackathon_id"),
    )

    submission: Mapped["Submission"] = relationship(
        "Submission", back_populates="evaluation_jobs"
    )
    snapshot: Mapped["SubmissionSnapshot"] = relationship(
        "SubmissionSnapshot", back_populates="evaluation_jobs"
    )
    results: Mapped[List["EvaluationResult"]] = relationship(
        "EvaluationResult",
        back_populates="job",
        foreign_keys="EvaluationResult.job_id",
        cascade="all, delete-orphan",
    )


class EvaluationResult(Base):
    """
    Subsystem C: Authoritative output of an evaluation attempt.
    Preserves full retry history across attempts.
    """
    __tablename__ = "evaluation_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    hackathon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hackathons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("submissions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rubric_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("submission_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    model_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    normalized_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    summary_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    has_insufficient_evidence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "job_id", "attempt_number", name="uq_evaluation_results_job_attempt"
        ),
    )

    job: Mapped["EvaluationJob"] = relationship(
        "EvaluationJob", back_populates="results", foreign_keys=[job_id]
    )
    criterion_scores: Mapped[List["EvaluationCriterionScore"]] = relationship(
        "EvaluationCriterionScore",
        back_populates="evaluation_result",
        cascade="all, delete-orphan",
    )
    judge_reviews: Mapped[List["JudgeReview"]] = relationship(
        "JudgeReview", back_populates="evaluation_result"
    )


class EvaluationCriterionScore(Base):
    """Subsystem C: Criterion-level score and rationale awarded by model for a specific result attempt."""
    __tablename__ = "evaluation_criterion_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    evaluation_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rubric_criteria.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    awarded_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    normalized_criterion_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False
    )
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("1.00")
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "evidence_status IN ('verified', 'partial', 'missing')",
            name="chk_evaluation_criterion_scores_evidence_status",
        ),
    )

    evaluation_result: Mapped["EvaluationResult"] = relationship(
        "EvaluationResult", back_populates="criterion_scores"
    )
    evidence_references: Mapped[List["EvidenceReference"]] = relationship(
        "EvidenceReference",
        back_populates="criterion_score",
        cascade="all, delete-orphan",
    )


class EvidenceReference(Base):
    """Subsystem C: Verifiable line-level citations grounding the score in the snapshot."""
    __tablename__ = "evidence_references"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    criterion_score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_criterion_scores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    start_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    is_verified_in_repo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    verification_failure_reason: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    criterion_score: Mapped["EvaluationCriterionScore"] = relationship(
        "EvaluationCriterionScore", back_populates="evidence_references"
    )


class JudgeReview(Base):
    """Subsystem C: Human judge override and decision record."""
    __tablename__ = "judge_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evaluation_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_results.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    judge_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    original_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    adjusted_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    overall_feedback: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "decision IN ('accepted', 'adjusted', 'rejected')",
            name="chk_judge_reviews_decision",
        ),
    )

    evaluation_result: Mapped["EvaluationResult"] = relationship(
        "EvaluationResult", back_populates="judge_reviews"
    )
    criterion_scores: Mapped[List["JudgeCriterionScore"]] = relationship(
        "JudgeCriterionScore",
        back_populates="judge_review",
        cascade="all, delete-orphan",
    )


class JudgeCriterionScore(Base):
    """Subsystem C: Criterion-level adjustments by human judge with mandatory written rationale."""
    __tablename__ = "judge_criterion_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    judge_review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("judge_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rubric_criteria.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    original_awarded_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    adjusted_awarded_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    judge_notes: Mapped[str] = mapped_column(Text, nullable=False)

    judge_review: Mapped["JudgeReview"] = relationship(
        "JudgeReview", back_populates="criterion_scores"
    )


class OrganizationIntegration(Base):
    """
    Subsystem C: Encrypted credential vault storing GitHub tokens and App installations per tenant.
    Tokens are encrypted at rest with AES-256-GCM.
    """
    __tablename__ = "organization_integrations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="github"
    )
    credential_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pat"
    )
    encrypted_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(
        String(50), nullable=False, default="master_v1"
    )
    token_preview: Mapped[str] = mapped_column(String(20), nullable=False)
    scopes: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
        server_default='["contents:read", "metadata:read"]',
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "credential_type IN ('pat', 'github_app')",
            name="chk_org_integrations_credential_type",
        ),
        Index(
            "uq_org_integrations_org_provider_active",
            "organization_id",
            "provider",
            unique=True,
            postgresql_where=(revoked_at.is_(None)),
        ),
    )


class HackathonJudge(Base):
    """Subsystem C: Event-scoped judge assignments mapping users to specific hackathons."""
    __tablename__ = "hackathon_judges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    hackathon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hackathons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "hackathon_id", "user_id", name="uq_hackathon_judges_hackathon_user"
        ),
    )
