from decimal import Decimal
import pytest
from apps.api.modules.evaluations.scoring_calculator import (
    CriterionInput,
    CriterionScoreResult,
    EvaluationScoreResult,
    ScoringMode,
    calculate_evaluation_scores,
    validate_criteria_weights,
)


def test_mode_a_offset_normalized_minimum_and_maximum():
    """Mode A: min_score awards exactly 0.00%, max_score awards exactly 100.00%."""
    # Minimum score
    min_criteria = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("0.4000"),
            min_score=Decimal("2.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("2.00"),
        ),
        CriterionInput(
            criterion_id="c2",
            weight=Decimal("0.6000"),
            min_score=Decimal("1.00"),
            max_score=Decimal("5.00"),
            awarded_score=Decimal("1.00"),
        ),
    ]
    res_min = calculate_evaluation_scores(min_criteria, scoring_mode=ScoringMode.OFFSET_NORMALIZED)
    assert res_min.normalized_score == Decimal("0.00")
    assert res_min.raw_score == Decimal("3.00")
    assert res_min.criterion_scores[0].normalized_criterion_score == Decimal("0.0000")
    assert res_min.criterion_scores[1].normalized_criterion_score == Decimal("0.0000")

    # Maximum score
    max_criteria = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("0.4000"),
            min_score=Decimal("2.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("10.00"),
        ),
        CriterionInput(
            criterion_id="c2",
            weight=Decimal("0.6000"),
            min_score=Decimal("1.00"),
            max_score=Decimal("5.00"),
            awarded_score=Decimal("5.00"),
        ),
    ]
    res_max = calculate_evaluation_scores(max_criteria, scoring_mode=ScoringMode.OFFSET_NORMALIZED)
    assert res_max.normalized_score == Decimal("100.00")
    assert res_max.raw_score == Decimal("15.00")
    assert res_max.criterion_scores[0].normalized_criterion_score == Decimal("1.0000")
    assert res_max.criterion_scores[1].normalized_criterion_score == Decimal("1.0000")


def test_mode_a_offset_normalized_midpoint():
    """Mode A: halfway between min and max awards exactly 50.00%."""
    criteria = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("0.5000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("5.00"),
        ),
        CriterionInput(
            criterion_id="c2",
            weight=Decimal("0.5000"),
            min_score=Decimal("10.00"),
            max_score=Decimal("20.00"),
            awarded_score=Decimal("15.00"),
        ),
    ]
    res = calculate_evaluation_scores(criteria, scoring_mode=ScoringMode.OFFSET_NORMALIZED)
    assert res.normalized_score == Decimal("50.00")
    assert res.raw_score == Decimal("20.00")


def test_mode_b_raw_proportional():
    """Mode B: Proportional credit S_i / max_score."""
    criteria = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("0.5000"),
            min_score=Decimal("2.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("5.00"),  # 5/10 = 0.5
        ),
        CriterionInput(
            criterion_id="c2",
            weight=Decimal("0.5000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("20.00"),
            awarded_score=Decimal("16.00"),  # 16/20 = 0.8
        ),
    ]
    # In Mode B: 0.5 * 0.5 + 0.8 * 0.5 = 0.25 + 0.40 = 0.65 -> 65.00%
    # Note: In Mode A, c1 would be (5-2)/(10-2) = 3/8 = 0.375
    res_b = calculate_evaluation_scores(criteria, scoring_mode=ScoringMode.RAW_PROPORTIONAL)
    assert res_b.normalized_score == Decimal("65.00")
    assert res_b.raw_score == Decimal("21.00")
    assert res_b.criterion_scores[0].normalized_criterion_score == Decimal("0.5000")
    assert res_b.criterion_scores[1].normalized_criterion_score == Decimal("0.8000")


def test_rounding_half_up_boundary_cases():
    """Verify ROUND_HALF_UP behavior on exact midpoint boundaries (e.g., .455 vs .454)."""
    # Target total = 85.455% -> should round up to 85.46%
    # Let total = 85.455. With 1 criterion of weight 1.0, max=1000, awarded=854.55
    criteria_up = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("1.0000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("1000.00"),
            awarded_score=Decimal("854.55"),
        )
    ]
    res_up = calculate_evaluation_scores(criteria_up, scoring_mode=ScoringMode.OFFSET_NORMALIZED)
    assert res_up.normalized_score == Decimal("85.46")

    # Target total = 85.454% -> should round down to 85.45%
    criteria_down = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("1.0000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("1000.00"),
            awarded_score=Decimal("854.54"),
        )
    ]
    res_down = calculate_evaluation_scores(criteria_down, scoring_mode=ScoringMode.OFFSET_NORMALIZED)
    assert res_down.normalized_score == Decimal("85.45")


def test_strict_prohibition_of_floats():
    """Strictly prohibit binary floats to prevent non-deterministic precision drift."""
    # Passing float into awarded_score
    with pytest.raises(TypeError, match="Floating-point values are strictly prohibited"):
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("1.0000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=5.5,  # float
        )

    # Passing float into weight
    with pytest.raises(TypeError, match="Floating-point values are strictly prohibited"):
        CriterionInput(
            criterion_id="c1",
            weight=0.5,  # float
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("5.00"),
        )

    # Passing float into min_score
    with pytest.raises(TypeError, match="Floating-point values are strictly prohibited"):
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("1.0000"),
            min_score=0.0,  # float
            max_score=Decimal("10.00"),
            awarded_score=Decimal("5.00"),
        )

    # Passing float into max_score
    with pytest.raises(TypeError, match="Floating-point values are strictly prohibited"):
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("1.0000"),
            min_score=Decimal("0.00"),
            max_score=10.0,  # float
            awarded_score=Decimal("5.00"),
        )


def test_all_output_types_are_decimals():
    """Assert all calculations and outputs use Decimal, never IEEE-754 float."""
    criteria = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("0.3333"),
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("7.00"),
        ),
        CriterionInput(
            criterion_id="c2",
            weight=Decimal("0.6667"),
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("8.50"),
        ),
    ]
    result = calculate_evaluation_scores(criteria, scoring_mode=ScoringMode.OFFSET_NORMALIZED)

    assert isinstance(result.raw_score, Decimal)
    assert isinstance(result.normalized_score, Decimal)
    for c in result.criterion_scores:
        assert isinstance(c.awarded_score, Decimal)
        assert isinstance(c.normalized_criterion_score, Decimal)
        assert isinstance(c.weighted_score, Decimal)
        assert isinstance(c.confidence_score, Decimal)
        assert not isinstance(c.awarded_score, float)
        assert not isinstance(c.normalized_criterion_score, float)
        assert not isinstance(c.weighted_score, float)


def test_rubric_weight_sum_validation_pass_and_fail():
    """Assert criteria weight sum validator passes within 1.0000 ± 0.0001 and fails outside."""
    # Exact 1.0000 -> passes
    c_exact = [
        CriterionInput(criterion_id="1", weight=Decimal("0.5000"), awarded_score=Decimal("5")),
        CriterionInput(criterion_id="2", weight=Decimal("0.5000"), awarded_score=Decimal("5")),
    ]
    validate_criteria_weights(c_exact)

    # Sum 1.0001 (within +0.0001 tolerance) -> passes
    c_upper = [
        CriterionInput(criterion_id="1", weight=Decimal("0.5001"), awarded_score=Decimal("5")),
        CriterionInput(criterion_id="2", weight=Decimal("0.5000"), awarded_score=Decimal("5")),
    ]
    validate_criteria_weights(c_upper)

    # Sum 0.9999 (within -0.0001 tolerance) -> passes
    c_lower = [
        CriterionInput(criterion_id="1", weight=Decimal("0.4999"), awarded_score=Decimal("5")),
        CriterionInput(criterion_id="2", weight=Decimal("0.5000"), awarded_score=Decimal("5")),
    ]
    validate_criteria_weights(c_lower)

    # Sum 1.0010 (exceeds +0.0001 tolerance) -> fails
    c_fail_high = [
        CriterionInput(criterion_id="1", weight=Decimal("0.5010"), awarded_score=Decimal("5")),
        CriterionInput(criterion_id="2", weight=Decimal("0.5000"), awarded_score=Decimal("5")),
    ]
    with pytest.raises(ValueError, match="Rubric criteria weights must sum to 1.0000 ± 0.0001"):
        validate_criteria_weights(c_fail_high)

    # Sum 0.9990 (exceeds -0.0001 tolerance) -> fails
    c_fail_low = [
        CriterionInput(criterion_id="1", weight=Decimal("0.4990"), awarded_score=Decimal("5")),
        CriterionInput(criterion_id="2", weight=Decimal("0.5000"), awarded_score=Decimal("5")),
    ]
    with pytest.raises(ValueError, match="Rubric criteria weights must sum to 1.0000 ± 0.0001"):
        validate_criteria_weights(c_fail_low)


def test_score_bounds_rejection():
    """Rejects awarded scores strictly outside [min_score, max_score]."""
    # Score below min_score
    c_below = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("1.0000"),
            min_score=Decimal("2.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("1.99"),
        )
    ]
    with pytest.raises(ValueError, match="out of bounds"):
        calculate_evaluation_scores(c_below)

    # Score above max_score
    c_above = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("1.0000"),
            min_score=Decimal("2.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("10.01"),
        )
    ]
    with pytest.raises(ValueError, match="out of bounds"):
        calculate_evaluation_scores(c_above)


def test_invalid_parameters_rejection():
    """Rejects min_score >= max_score, invalid weight, and unsupported scoring mode."""
    # min_score == max_score
    c_equal = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("1.0000"),
            min_score=Decimal("10.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("10.00"),
        )
    ]
    with pytest.raises(ValueError, match="min_score.*must be strictly less than max_score"):
        calculate_evaluation_scores(c_equal)

    # weight <= 0
    c_zero_weight = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("0.0000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("5.00"),
        ),
        CriterionInput(
            criterion_id="c2",
            weight=Decimal("1.0000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("5.00"),
        ),
    ]
    with pytest.raises(ValueError, match="weight.*must be strictly within"):
        calculate_evaluation_scores(c_zero_weight)

    # Unsupported scoring mode string
    c_valid = [
        CriterionInput(
            criterion_id="c1",
            weight=Decimal("1.0000"),
            min_score=Decimal("0.00"),
            max_score=Decimal("10.00"),
            awarded_score=Decimal("5.00"),
        )
    ]
    with pytest.raises(ValueError, match="Unsupported scoring_mode 'quantum_superposition'"):
        calculate_evaluation_scores(c_valid, scoring_mode="quantum_superposition")
