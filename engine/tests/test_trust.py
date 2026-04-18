"""
Phase 5E — Unit tests for the per-product trust scorer.

Tests cover:
  (a) compute_trust_score pure function: zero below minimum, formula correctness,
      clamping to 1.0, perfect-rate scaling.
  (b) tests_needed_for_threshold: returns 0 when already eligible,
      positive integer otherwise, converges to threshold.
  (c) Auto-approve eligibility boundary at 0.70.
"""
import math
import pytest

from engine.trust.scorer import (
    _AUTO_APPROVE_THRESHOLD,
    _MIN_TESTS,
    _NORMALIZER,
    compute_trust_score,
    tests_needed_for_threshold as _tests_needed,
)


# ---------------------------------------------------------------------------
# (a) compute_trust_score pure function
# ---------------------------------------------------------------------------

class TestComputeTrustScore:
    def test_zero_tests_returns_zero(self):
        assert compute_trust_score(0, 0) == 0.0

    def test_below_minimum_tests_returns_zero(self):
        """Fewer than _MIN_TESTS (3) completed → always 0.0."""
        assert compute_trust_score(1, 1) == 0.0
        assert compute_trust_score(2, 2) == 0.0

    def test_exactly_minimum_tests_positive(self):
        """3 tests, all positive — should be nonzero and < 1.0."""
        score = compute_trust_score(_MIN_TESTS, _MIN_TESTS)
        expected = 1.0 * math.log1p(_MIN_TESTS) / _NORMALIZER
        assert abs(score - expected) < 1e-9
        assert 0.0 < score < 1.0

    def test_formula_matches_manual_calculation(self):
        """10 tests, 8 positive: rate=0.8, scale=log(11)/log(11)=1.0 → 0.8."""
        score = compute_trust_score(10, 8)
        expected = 0.8 * math.log1p(10) / _NORMALIZER  # scale = 1.0 exactly
        assert abs(score - expected) < 1e-9

    def test_perfect_rate_at_10_tests_gives_1(self):
        """10 tests, 10 positive: 1.0 * 1.0 = 1.0."""
        score = compute_trust_score(10, 10)
        assert score == pytest.approx(1.0, abs=1e-9)

    def test_score_capped_at_1(self):
        """
        Even with 100% positive rate and many tests, score must not exceed 1.0.
        (log1p(100)/log1p(10) > 1, so capping is required.)
        """
        score = compute_trust_score(100, 100)
        assert score == 1.0

    def test_zero_positive_gives_zero_score(self):
        """Zero successes → rate 0 → score 0."""
        assert compute_trust_score(5, 0) == 0.0

    def test_score_increases_with_more_positive_tests(self):
        """Monotonicity: more positives at same total → higher score."""
        low = compute_trust_score(5, 1)
        mid = compute_trust_score(5, 3)
        high = compute_trust_score(5, 5)
        assert low < mid < high

    def test_score_increases_with_more_total_tests_same_rate(self):
        """Monotonicity: same win rate but more evidence → higher score."""
        s5 = compute_trust_score(5, 5)
        s10 = compute_trust_score(10, 10)
        assert s5 < s10

    def test_score_in_valid_range(self):
        """Score is always in [0.0, 1.0] for any reasonable input."""
        cases = [
            (0, 0), (1, 0), (2, 2), (3, 1), (3, 3),
            (5, 3), (10, 7), (10, 10), (50, 40), (100, 100),
        ]
        for tc, tp in cases:
            score = compute_trust_score(tc, tp)
            assert 0.0 <= score <= 1.0, f"Out of range for ({tc}, {tp}): {score}"


# ---------------------------------------------------------------------------
# (b) tests_needed_for_threshold
# ---------------------------------------------------------------------------

class TestTestsNeededForThreshold:
    def test_already_eligible_returns_zero(self):
        """10 tests, 10 positive = score 1.0 → needs 0 more."""
        assert _tests_needed(10, 10) == 0

    def test_at_threshold_returns_zero(self):
        """Exactly at threshold → 0 needed."""
        # Find a case where score >= 0.70
        # 10 tests, 8 positive: 0.8 * 1.0 = 0.80 >= 0.70
        assert _tests_needed(10, 8) == 0

    def test_zero_tests_needs_positive_count(self):
        """Starting fresh: needs some positive tests before eligibility."""
        needed = _tests_needed(0, 0)
        assert needed > 0

    def test_convergence_after_adding_needed_tests(self):
        """
        Adding `needed` positive tests should push score to >= threshold.
        Verify the return value actually satisfies the contract.
        """
        tc, tp = 3, 1
        needed = _tests_needed(tc, tp)
        new_tc = tc + needed
        new_tp = tp + needed
        final_score = compute_trust_score(new_tc, new_tp)
        assert final_score >= _AUTO_APPROVE_THRESHOLD, (
            f"After adding {needed} tests: score={final_score:.4f} still below threshold"
        )

    def test_needed_decreases_as_positive_tests_accumulate(self):
        """More positive history → fewer tests needed to reach threshold."""
        n3 = _tests_needed(5, 0)
        n5 = _tests_needed(5, 3)
        assert n3 >= n5

    def test_returns_non_negative_integer(self):
        """Return value must always be a non-negative integer."""
        for tc, tp in [(0, 0), (1, 0), (3, 2), (5, 5)]:
            needed = _tests_needed(tc, tp)
            assert isinstance(needed, int)
            assert needed >= 0


# ---------------------------------------------------------------------------
# (c) Auto-approve eligibility boundary
# ---------------------------------------------------------------------------

class TestAutoApproveEligibility:
    def test_threshold_constant_is_070(self):
        assert _AUTO_APPROVE_THRESHOLD == 0.70

    def test_score_below_threshold_not_eligible(self):
        """3 tests, 1 positive: low score, not eligible."""
        score = compute_trust_score(3, 1)
        assert score < _AUTO_APPROVE_THRESHOLD

    def test_score_above_threshold_eligible(self):
        """10 tests, 9 positive: score > 0.70."""
        score = compute_trust_score(10, 9)
        assert score >= _AUTO_APPROVE_THRESHOLD

    def test_boundary_at_10_tests_8_positive(self):
        """10 tests, 8 positive = 0.80 — just above threshold."""
        score = compute_trust_score(10, 8)
        assert score >= _AUTO_APPROVE_THRESHOLD

    def test_minimum_tests_constant(self):
        assert _MIN_TESTS == 3

    def test_normalizer_is_log1p_10(self):
        assert abs(_NORMALIZER - math.log1p(10)) < 1e-12
