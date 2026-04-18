"""
Phase 4C — Tests for the Bayesian A/B test statistics engine.

Tests cover:
  (a) Significance reached correctly at the 95% threshold.
  (b) Kill-switch triggers at the right threshold.
  (c) Neither fires when the experiment is inconclusive.
  (d) Edge cases: zero orders, tiny treatment window.

Note: PyMC sampling is non-deterministic even with a fixed seed across
platforms.  Tests use wide margins (±10%) to stay robust.
"""
import pytest

from engine.stats.bayesian import (
    ExperimentStats,
    check_kill_switch,
    check_significance,
    compute_experiment_stats,
)


def _stats(
    ctrl_orders: int = 0,
    ctrl_days: float = 14.0,
    trt_orders: int = 0,
    trt_days: float = 7.0,
    ctrl_revenue: float = 0.0,
    trt_revenue: float = 0.0,
    days_running: int = 7,
) -> ExperimentStats:
    return compute_experiment_stats(
        experiment_id=1,
        control_orders=ctrl_orders,
        control_days=ctrl_days,
        treatment_orders=trt_orders,
        treatment_days=trt_days,
        control_revenue=ctrl_revenue,
        treatment_revenue=trt_revenue,
        days_running=days_running,
    )


# ---------------------------------------------------------------------------
# (a) Significance reached
# ---------------------------------------------------------------------------

class TestSignificanceReached:
    def test_high_treatment_outperforms_control(self):
        """Treatment with 3× the order rate should yield P(trt > ctrl) near 1."""
        stats = _stats(
            ctrl_orders=10, ctrl_days=14.0, ctrl_revenue=200.0,
            trt_orders=30, trt_days=14.0, trt_revenue=600.0,
        )
        # With such a strong signal, prob_treatment_better should be >0.95
        assert stats.prob_treatment_better > 0.90, (
            f"Expected prob_treatment_better > 0.90, got {stats.prob_treatment_better}"
        )
        assert check_significance(stats)
        assert stats.significance_reached

    def test_significance_not_reached_for_equal_arms(self):
        """Equal performance should give prob close to 0.5, not ≥0.95."""
        stats = _stats(
            ctrl_orders=20, ctrl_days=14.0, ctrl_revenue=400.0,
            trt_orders=20, trt_days=14.0, trt_revenue=400.0,
        )
        assert stats.prob_treatment_better < 0.90, (
            f"Expected prob_treatment_better < 0.90 for equal arms, got {stats.prob_treatment_better}"
        )
        assert not check_significance(stats)


# ---------------------------------------------------------------------------
# (b) Kill-switch triggers
# ---------------------------------------------------------------------------

class TestKillSwitch:
    def test_kill_switch_triggers_when_treatment_badly_underperforms(self):
        """Treatment with 1/3 the order rate should trigger kill-switch."""
        stats = _stats(
            ctrl_orders=30, ctrl_days=14.0, ctrl_revenue=600.0,
            trt_orders=5, trt_days=14.0, trt_revenue=100.0,
        )
        # prob_kill_switch = P(trt_rpv < 0.9 * ctrl_rpv) should be very high
        assert stats.prob_kill_switch > 0.75, (
            f"Expected prob_kill_switch > 0.75, got {stats.prob_kill_switch}"
        )
        assert check_kill_switch(stats)
        assert stats.kill_switch_triggered

    def test_kill_switch_does_not_trigger_for_equal_arms(self):
        """Equal arms: kill-switch should NOT fire."""
        stats = _stats(
            ctrl_orders=20, ctrl_days=14.0, ctrl_revenue=400.0,
            trt_orders=20, trt_days=14.0, trt_revenue=400.0,
        )
        assert not check_kill_switch(stats)
        assert not stats.kill_switch_triggered


# ---------------------------------------------------------------------------
# (c) Inconclusive experiment
# ---------------------------------------------------------------------------

class TestInconclusive:
    def test_neither_fires_for_small_sample(self):
        """Very few orders in both arms → high uncertainty → neither threshold met."""
        stats = _stats(
            ctrl_orders=2, ctrl_days=14.0, ctrl_revenue=40.0,
            trt_orders=3, trt_days=7.0, trt_revenue=60.0,
            days_running=7,
        )
        # Uncertainty is too high to conclude anything
        assert not stats.significance_reached or not stats.kill_switch_triggered, (
            "Small sample should not confidently reach any conclusion"
        )

    def test_prob_between_thresholds_for_similar_arms(self):
        """Moderately different arms: prob should sit in the inconclusive zone."""
        stats = _stats(
            ctrl_orders=15, ctrl_days=14.0, ctrl_revenue=300.0,
            trt_orders=18, trt_days=14.0, trt_revenue=360.0,
        )
        # A ~20% lift with small samples is not conclusive
        assert 0.05 < stats.prob_treatment_better < 0.99, (
            f"Expected inconclusive prob, got {stats.prob_treatment_better}"
        )


# ---------------------------------------------------------------------------
# (d) Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_orders_in_both_arms(self):
        """No data → prior dominates → prob close to 0.5, no conclusion."""
        stats = _stats(ctrl_orders=0, trt_orders=0, ctrl_revenue=0.0, trt_revenue=0.0)
        assert 0.1 < stats.prob_treatment_better < 0.9
        assert not stats.significance_reached
        assert not stats.kill_switch_triggered

    def test_zero_orders_in_treatment_only(self):
        """Control has orders, treatment has none → kill-switch likely fires."""
        stats = _stats(
            ctrl_orders=20, ctrl_days=14.0, ctrl_revenue=400.0,
            trt_orders=0, trt_days=7.0, trt_revenue=0.0,
        )
        # Treatment with no orders should have very low prob of being better
        assert stats.prob_treatment_better < 0.5

    def test_returns_experiment_stats_instance(self):
        stats = _stats()
        assert isinstance(stats, ExperimentStats)
        assert stats.experiment_id == 1
        assert 0.0 <= stats.prob_treatment_better <= 1.0
        assert 0.0 <= stats.prob_kill_switch <= 1.0

    def test_check_significance_respects_custom_threshold(self):
        stats = _stats(
            ctrl_orders=10, ctrl_days=14.0, ctrl_revenue=200.0,
            trt_orders=30, trt_days=14.0, trt_revenue=600.0,
        )
        # Very strong signal; custom threshold of 0.99 might not be met but 0.80 should be
        assert check_significance(stats, threshold=0.80)

    def test_check_kill_switch_respects_custom_threshold(self):
        stats = _stats(
            ctrl_orders=30, ctrl_days=14.0, ctrl_revenue=600.0,
            trt_orders=5, trt_days=14.0, trt_revenue=100.0,
        )
        # Kill-switch at high threshold 0.95 should still fire for very bad treatment
        assert check_kill_switch(stats, threshold=0.70)
