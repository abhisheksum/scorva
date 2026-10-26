"""
Scorva Structured Output Validator & Schema Verification Engine.

Enforces strict Pydantic schema validation, rubric criterion completeness,
numerical score bounds, line-level citation verification, and bounded retry
mechanisms for AI-generated evaluations.
"""

from decimal import Decimal
import json
import logging
import math
from typing import Any, Dict, List, Literal, Optional, Set, Union
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.api.modules.evaluations.ai_provider import (
    AIProviderClient,
    AIProviderError,
    AIProviderFormatError,
    AIProviderSSRFError,
    AIProviderTimeoutError,
)

logger = logging.getLogger("scorva.output_validator")


# ==============================================================================
# Validation Error Definitions
# ==============================================================================

class AIEvaluationValidationError(Exception):
    """
    Raised when AI model output violates schema, rubric criteria,
    numerical bounds, or verifiable evidence citations.
    """
    def __init__(self, error_code: str, details: str, retryable: bool = True):
        super().__init__(f"[{error_code}] {details}")
        self.error_code = error_code
        self.details = details
        self.retryable = retryable


# ==============================================================================
# Pydantic Schemas for AI Output
# ==============================================================================

class AIEvidenceReferencePayload(BaseModel):
    """Line-level citation grounding an awarded score in repository evidence."""
    file_path: str = Field(..., min_length=1, max_length=500)
    start_line: Optional[int] = Field(None, ge=1)
    end_line: Optional[int] = Field(None, ge=1)
    snippet: str = Field(..., min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_line_range(self) -> "AIEvidenceReferencePayload":
        if self.start_line is not None and self.end_line is not None:
            if self.start_line > self.end_line:
                raise ValueError(
                    f"start_line ({self.start_line}) cannot be greater than end_line ({self.end_line})."
                )
        return self


class AICriterionScorePayload(BaseModel):
    """Criterion evaluation awarded by the model."""
    criterion_id: uuid.UUID
    awarded_score: Decimal
    confidence_score: Decimal = Field(default=Decimal("1.00"), ge=Decimal("0.00"), le=Decimal("1.00"))
    rationale: str = Field(..., min_length=10)
    evidence_status: Literal["verified", "partial", "missing"]
    evidence_references: List[AIEvidenceReferencePayload] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("awarded_score", "confidence_score", mode="before")
    @classmethod
    def validate_finite_decimal(cls, v: Any) -> Decimal:
        if v is None:
            raise ValueError("Score value cannot be None.")
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            raise ValueError(f"Score cannot be NaN or Infinity, got {v}")
        try:
            d = Decimal(str(v))
        except Exception as exc:
            raise ValueError(f"Invalid decimal value: {v}") from exc
        if not d.is_finite():
            raise ValueError(f"Score cannot be non-finite decimal: {d}")
        return d


class AIEvaluationOutputPayload(BaseModel):
    """
    Authoritative structured output schema produced by AI evaluation models.
    Strictly forbids extra fields, enforces criterion presence and non-empty summaries.
    """
    summary_assessment: str = Field(..., min_length=10)
    has_insufficient_evidence: bool = False
    criterion_scores: List[AICriterionScorePayload] = Field(..., min_length=1)

    model_config = ConfigDict(extra="forbid")


# ==============================================================================
# Pure Validation Functions
# ==============================================================================

def validate_ai_evaluation_output(
    raw_output: Union[str, Dict[str, Any]],
    rubric_criteria: List[Any],
    evidence_index: Optional[Any] = None,
) -> AIEvaluationOutputPayload:
    """
    Validates model output against:
    1. Structural Pydantic JSON Schema (rejects extra/missing/invalid fields).
    2. Criterion completeness and uniqueness (every criterion present, no duplicates, no unknown).
    3. Numerical score bounds ([min_score, max_score]).
    4. Missing evidence rule (missing evidence must receive min_score).
    5. Evidence citation existence (cited files and line ranges must exist in evidence index).
    """
    # 1. Parse JSON if string
    if isinstance(raw_output, str):
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise AIEvaluationValidationError(
                "MALFORMED_JSON",
                f"Failed to parse raw output as JSON: {exc}",
                retryable=True,
            ) from exc
    elif isinstance(raw_output, dict):
        data = raw_output
    else:
        raise AIEvaluationValidationError(
            "INVALID_PAYLOAD_TYPE",
            f"Expected dict or JSON string, got {type(raw_output).__name__}",
            retryable=False,
        )

    # 2. Pydantic schema validation
    try:
        payload = AIEvaluationOutputPayload.model_validate(data)
    except Exception as exc:
        raise AIEvaluationValidationError(
            "SCHEMA_VALIDATION_ERROR",
            f"Model output violates Pydantic schema: {exc}",
            retryable=True,
        ) from exc

    # 3. Rubric Criterion Completeness & Uniqueness
    expected_map: Dict[uuid.UUID, Any] = {}
    for crit in rubric_criteria:
        crit_id_raw = getattr(crit, "id", None) or (crit.get("id") if isinstance(crit, dict) else None)
        crit_uuid = uuid.UUID(str(crit_id_raw))
        expected_map[crit_uuid] = crit

    expected_ids: Set[uuid.UUID] = set(expected_map.keys())
    reported_ids = [cs.criterion_id for cs in payload.criterion_scores]

    # Check for duplicate criteria
    if len(reported_ids) != len(set(reported_ids)):
        duplicates = [uid for uid in reported_ids if reported_ids.count(uid) > 1]
        raise AIEvaluationValidationError(
            "DUPLICATE_CRITERIA_DETECTED",
            f"Model output contains duplicate criterion IDs: {set(duplicates)}",
            retryable=True,
        )

    # Check for unknown criteria
    unknown_ids = set(reported_ids) - expected_ids
    if unknown_ids:
        raise AIEvaluationValidationError(
            "UNKNOWN_CRITERIA_DETECTED",
            f"Model output contains unknown criterion IDs not present in rubric: {unknown_ids}",
            retryable=True,
        )

    # Check for missing criteria
    missing_ids = expected_ids - set(reported_ids)
    if missing_ids:
        raise AIEvaluationValidationError(
            "MISSING_CRITERIA_DETECTED",
            f"Model output omitted required rubric criteria: {missing_ids}",
            retryable=True,
        )

    # 4. Numerical Score Bounds & Missing Evidence Rule
    has_missing_evidence = False

    for cs in payload.criterion_scores:
        crit = expected_map[cs.criterion_id]
        min_score = Decimal(str(getattr(crit, "min_score", None) or (crit.get("min_score") if isinstance(crit, dict) else Decimal("0.00"))))
        max_score = Decimal(str(getattr(crit, "max_score", None) or (crit.get("max_score") if isinstance(crit, dict) else Decimal("10.00"))))

        # Check score bounds
        if cs.awarded_score < min_score or cs.awarded_score > max_score:
            raise AIEvaluationValidationError(
                "SCORE_OUT_OF_BOUNDS",
                f"Awarded score {cs.awarded_score} is outside permissible bounds [{min_score}, {max_score}] for criterion {cs.criterion_id}.",
                retryable=True,
            )

        # Missing evidence rule
        if cs.evidence_status == "missing":
            has_missing_evidence = True
            if cs.awarded_score != min_score:
                raise AIEvaluationValidationError(
                    "MISSING_EVIDENCE_SCORE_MISMATCH",
                    f"Criterion {cs.criterion_id} has 'missing' evidence status but was awarded {cs.awarded_score} instead of min_score {min_score}.",
                    retryable=True,
                )

        # 5. Evidence Citation Verification
        if evidence_index and hasattr(evidence_index, "files") and evidence_index.files:
            for ref in cs.evidence_references:
                norm_path = ref.file_path.replace("\\", "/").strip().lstrip("/")
                if norm_path not in evidence_index.files and ref.file_path not in evidence_index.files:
                    raise AIEvaluationValidationError(
                        "FABRICATED_CITATION_FILE",
                        f"Cited file '{ref.file_path}' does not exist in repository evidence index.",
                        retryable=True,
                    )

                indexed_file = evidence_index.files.get(norm_path) or evidence_index.files.get(ref.file_path)
                if indexed_file and ref.end_line is not None:
                    if ref.end_line > indexed_file.total_lines:
                        raise AIEvaluationValidationError(
                            "INVALID_CITATION_LINE_RANGE",
                            f"Cited end_line {ref.end_line} exceeds total lines ({indexed_file.total_lines}) in file '{ref.file_path}'.",
                            retryable=True,
                        )

    if has_missing_evidence and not payload.has_insufficient_evidence:
        payload.has_insufficient_evidence = True

    return payload


# ==============================================================================
# Bounded Retry Execution Pipeline
# ==============================================================================

async def execute_evaluation_with_retry(
    provider_client: AIProviderClient,
    prompt: str,
    schema: Dict[str, Any],
    model_name: str,
    rubric_criteria: List[Any],
    evidence_index: Optional[Any] = None,
    timeout_seconds: float = 120.0,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    max_retries: int = 1,
) -> AIEvaluationOutputPayload:
    """
    Executes model inference and validates output against schema, rubric criteria,
    score bounds, and verifiable evidence citations.
    Performs at most one bounded retry for recoverable parse/schema failures with temperature 0.0.
    Fails closed immediately on SSRF, network policy, or unrecoverable errors.
    """
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        is_retry = attempt > 0

        current_prompt = prompt
        current_temp = 0.0 if is_retry else temperature

        if is_retry and last_error:
            current_prompt = (
                f"{prompt}\n\n"
                f"CRITICAL CORRECTION REQUIRED:\n"
                f"Your previous response was rejected due to validation errors:\n"
                f"{str(last_error)}\n"
                f"You must strictly satisfy all schema requirements:\n"
                f"- Output valid JSON only, conforming exactly to the schema.\n"
                f"- Include EVERY required criterion ID exactly once with no duplicates.\n"
                f"- Ensure each awarded score is strictly within [min_score, max_score].\n"
                f"- For missing evidence, award min_score with status 'missing'.\n"
                f"- Cite only files that exist in the repository evidence."
            )

        try:
            raw_response = await provider_client.generate_evaluation(
                prompt=current_prompt,
                schema=schema,
                model_name=model_name,
                timeout_seconds=timeout_seconds,
                temperature=current_temp,
                max_tokens=max_tokens,
            )
        except AIProviderSSRFError:
            # SSRF violations must never be retried
            raise
        except (AIProviderFormatError, AIProviderTimeoutError) as exc:
            last_error = exc
            if attempt < max_retries and getattr(exc, "retryable", False):
                logger.warning(
                    "Recoverable AI provider error on attempt %d: %s. Retrying with temperature 0.0...",
                    attempt + 1,
                    exc,
                )
                continue
            raise AIEvaluationValidationError(
                "EVAL_PARSE_ERROR",
                f"AI provider failed after {attempt + 1} attempt(s): {exc}",
                retryable=False,
            ) from exc
        except AIProviderError:
            # Other non-retryable provider errors fail closed
            raise

        # Validate structured output against rubric criteria and evidence
        try:
            validated_payload = validate_ai_evaluation_output(
                raw_output=raw_response,
                rubric_criteria=rubric_criteria,
                evidence_index=evidence_index,
            )
            return validated_payload
        except AIEvaluationValidationError as val_exc:
            last_error = val_exc
            if attempt < max_retries and val_exc.retryable:
                logger.warning(
                    "Schema/rubric validation failure on attempt %d: %s. Retrying with temperature 0.0...",
                    attempt + 1,
                    val_exc,
                )
                continue
            raise AIEvaluationValidationError(
                "EVAL_PARSE_ERROR",
                f"Evaluation failed schema validation after {attempt + 1} attempt(s): {val_exc.details}",
                retryable=False,
            ) from val_exc

    raise AIEvaluationValidationError(
        "EVAL_PARSE_ERROR",
        f"Evaluation failed after {max_retries + 1} attempts: {last_error}",
        retryable=False,
    )
