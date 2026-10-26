"""
Deterministic Score Normalization Calculator for Scorva AI Evaluation Engine.

Guarantees 100% reproducible score normalization across evaluation runs.
Strictly prohibits IEEE-754 binary floating-point calculations to avoid non-deterministic drift.
All arithmetic uses Python decimal.Decimal with ROUND_HALF_UP rounding.
"""

from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import uuid
from pydantic import BaseModel, ConfigDict, field_validator


TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
WEIGHT_SUM_TOLERANCE = Decimal("0.0001")
EXPECTED_WEIGHT_SUM = Decimal("1.0000")


class ScoringMode(str, Enum):
    OFFSET_NORMALIZED = "offset_normalized"
    RAW_PROPORTIONAL = "raw_proportional"


def assert_not_float(value: Any, param_name: str) -> None:
    """Strictly prohibit binary float types to prevent IEEE-754 precision drift."""
    if isinstance(value, float):
        raise TypeError(
            f"Floating-point values are strictly prohibited for '{param_name}' to prevent "
            f"precision drift. Provide decimal.Decimal or string/integer representation, got float ({value})."
        )


def to_decimal(val: Union[Decimal, int, str, Any], param_name: str) -> Decimal:
    """Convert input to Decimal while rejecting binary float."""
    assert_not_float(val, param_name)
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception as exc:
        raise ValueError(f"Cannot convert '{param_name}' value ({val}) to Decimal: {exc}") from exc


class CriterionInput(BaseModel):
    """Input definition and awarded score for a single rubric criterion."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    criterion_id: Union[uuid.UUID, str]
    title: Optional[str] = None
    weight: Decimal
    min_score: Decimal = Decimal("0.00")
    max_score: Decimal = Decimal("10.00")
    awarded_score: Decimal
    confidence_score: Decimal = Decimal("1.00")

    @field_validator("weight", "min_score", "max_score", "awarded_score", "confidence_score", mode="before")
    @classmethod
    def validate_decimal_types(cls, v: Any, info: Any) -> Decimal:
        assert_not_float(v, info.field_name)
        if isinstance(v, Decimal):
            return v
        return to_decimal(v, info.field_name)


class CriterionScoreResult(BaseModel):
    """Normalized output for a single rubric criterion."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    criterion_id: Union[uuid.UUID, str]
    title: Optional[str] = None
    awarded_score: Decimal
    normalized_criterion_score: Decimal  # 0.0000 to 1.0000
    weighted_score: Decimal
    confidence_score: Decimal


class EvaluationScoreResult(BaseModel):
    """Aggregate output of score calculator containing raw and normalized totals."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    scoring_mode: ScoringMode
    raw_score: Decimal  # Sum of awarded scores quantized to 2 decimal places
    normalized_score: Decimal  # 0.00 to 100.00 quantized to 2 decimal places (ROUND_HALF_UP)
    criterion_scores: List[CriterionScoreResult]


def validate_criteria_weights(criteria: List[CriterionInput]) -> None:
    """
    Asserts that the sum of criteria weights is 1.0000 ± 0.0001
    and that all criterion IDs are unique.
    Raises ValueError on breach.
    """
    if not criteria:
        raise ValueError("Cannot calculate score: rubric has no criteria.")

    seen_ids: set[str] = set()
    for c in criteria:
        cid = str(c.criterion_id)
        if cid in seen_ids:
            raise ValueError(f"Duplicate criterion_id '{cid}' detected in criteria list.")
        seen_ids.add(cid)

    total_weight = sum((c.weight for c in criteria), Decimal("0.0000"))
    diff = abs(total_weight - EXPECTED_WEIGHT_SUM)
    if diff > WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            f"Rubric criteria weights must sum to 1.0000 ± 0.0001, got sum = {total_weight} (diff = {diff})"
        )


def calculate_evaluation_scores(
    criteria: List[CriterionInput],
    scoring_mode: Union[ScoringMode, str] = ScoringMode.OFFSET_NORMALIZED,
) -> EvaluationScoreResult:
    """
    Calculate deterministic raw and normalized evaluation scores.

    Mode A (offset_normalized):
        N_i = (S_i - min_i) / (max_i - min_i)
        Normalized Total = sum(N_i * weight_i) * 100

    Mode B (raw_proportional):
        P_i = S_i / max_i
        Normalized Total = sum(P_i * weight_i) * 100

    All math is performed using decimal.Decimal.
    Final total is rounded using ROUND_HALF_UP to 2 decimal places.
    """
    if isinstance(scoring_mode, str):
        try:
            scoring_mode = ScoringMode(scoring_mode.lower())
        except ValueError:
            raise ValueError(
                f"Unsupported scoring_mode '{scoring_mode}'. "
                f"Allowed modes: {[m.value for m in ScoringMode]}"
            )

    # 1. Validate weight sum invariant
    validate_criteria_weights(criteria)

    raw_score_sum = Decimal("0.00")
    total_weighted_normalized = Decimal("0.00000000")
    criterion_results: List[CriterionScoreResult] = []

    for c in criteria:
        # 2. Strict boundary and parameter checks
        if c.weight <= Decimal("0.0000") or c.weight > Decimal("1.0000"):
            raise ValueError(
                f"Criterion '{c.criterion_id}' weight ({c.weight}) must be strictly within (0.0000, 1.0000]."
            )

        if c.min_score >= c.max_score:
            raise ValueError(
                f"Criterion '{c.criterion_id}' min_score ({c.min_score}) must be strictly less than "
                f"max_score ({c.max_score})."
            )

        if c.awarded_score < c.min_score or c.awarded_score > c.max_score:
            raise ValueError(
                f"Awarded score {c.awarded_score} is out of bounds [{c.min_score}, {c.max_score}] "
                f"for criterion '{c.criterion_id}'."
            )

        raw_score_sum += c.awarded_score

        # 3. Mode-specific normalized criterion calculation
        if scoring_mode == ScoringMode.OFFSET_NORMALIZED:
            # Mode A: N_i = (S_i - min) / (max - min)
            score_range = c.max_score - c.min_score
            normalized_c = (c.awarded_score - c.min_score) / score_range
        else:
            # Mode B: P_i = S_i / max
            if c.max_score <= Decimal("0.00"):
                raise ValueError(
                    f"Criterion '{c.criterion_id}' max_score ({c.max_score}) must be positive for "
                    f"raw_proportional scoring."
                )
            normalized_c = c.awarded_score / c.max_score

        weighted_c = normalized_c * c.weight
        total_weighted_normalized += weighted_c

        criterion_results.append(
            CriterionScoreResult(
                criterion_id=c.criterion_id,
                title=c.title,
                awarded_score=c.awarded_score.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
                normalized_criterion_score=normalized_c.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP),
                weighted_score=weighted_c.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP),
                confidence_score=c.confidence_score.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
            )
        )

    # 4. Final total calculation with ROUND_HALF_UP
    normalized_percentage = total_weighted_normalized * Decimal("100")
    final_normalized_score = normalized_percentage.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    final_raw_score = raw_score_sum.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    return EvaluationScoreResult(
        scoring_mode=scoring_mode,
        raw_score=final_raw_score,
        normalized_score=final_normalized_score,
        criterion_scores=criterion_results,
    )
