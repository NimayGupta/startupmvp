"""
Phase 4C — Bayesian A/B Test Statistics Engine

Uses PyMC to compute posterior distributions over experiment outcomes.

Statistical model
-----------------
Conversion model  : Gamma-Poisson conjugate.
                    Order arrivals modelled as a Poisson process; the rate λ
                    has a Gamma(2, 0.5) prior (weakly informative; ~4 orders/day).
                    Posterior after observing n orders over d days:
                      λ | data ~ Gamma(2 + n, 0.5 + d)

RPV model         : λ × average_order_value (deterministic scaling).
                    Comparing RPV across arms captures both conversion rate
                    and order-value effects in a single metric.

Stopping rules
--------------
Kill switch   : P(trt_rpv < 0.9 × ctrl_rpv) > 0.80
Significance  : P(trt_rpv > ctrl_rpv) > 0.95
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_N_SAMPLES = 10_000
_RNG_SEED = 42
_GAMMA_PRIOR_ALPHA = 2.0   # shape
_GAMMA_PRIOR_BETA = 0.5    # rate  (mean = alpha/beta = 4 orders/day)

# ---------------------------------------------------------------------------
# PyMC is the primary backend (Docker / Linux).  Fall back to NumPy on
# platforms where PyMC or its transitive deps (arviz, scipy) can't import.
# The math is identical: both sample from the analytic Gamma posterior.
# ---------------------------------------------------------------------------
try:
    import pymc as pm  # type: ignore[import]
    _HAS_PYMC = True
    logger.debug("PyMC backend loaded (version %s)", pm.__version__)
except Exception:
    pm = None  # type: ignore[assignment]
    _HAS_PYMC = False
    logger.info("PyMC not available — using NumPy Gamma sampler (identical math)")


class ExperimentStats(BaseModel):
    experiment_id: int
    control_n: int            # orders (proxy for sessions) in control period
    treatment_n: int          # orders in treatment period
    control_conversions: int  # = control_n (Poisson model: all observations are conversions)
    treatment_conversions: int
    control_rpv: float        # posterior mean daily RPV for control
    treatment_rpv: float      # posterior mean daily RPV for treatment
    prob_treatment_better: float   # P(trt_rpv > ctrl_rpv)
    prob_kill_switch: float        # P(trt_rpv < 0.9 × ctrl_rpv)
    significance_reached: bool
    kill_switch_triggered: bool
    days_running: int


def compute_experiment_stats(
    experiment_id: int,
    control_orders: int,
    control_days: float,
    treatment_orders: int,
    treatment_days: float,
    control_revenue: float,
    treatment_revenue: float,
    days_running: int,
    significance_threshold: float = 0.95,
    kill_switch_threshold: float = 0.80,
    kill_switch_rpv_ratio: float = 0.90,
) -> ExperimentStats:
    """
    Compute Bayesian A/B test statistics using PyMC.

    Uses a Gamma-Poisson conjugate model.  Because the posterior is analytic,
    we use ``sample_prior_predictive`` on a model whose parameters are set to
    the posterior values — no MCMC needed, fast and exact.

    Args:
        experiment_id: DB primary key of the experiment.
        control_orders: Number of orders in the pre-experiment control window.
        control_days: Length of the control window in days.
        treatment_orders: Number of orders since the experiment started.
        treatment_days: Days elapsed since the experiment started (float).
        control_revenue: Total revenue in the control window.
        treatment_revenue: Total revenue in the treatment window.
        days_running: Integer days since experiment activation (for display).
        significance_threshold: P(trt_rpv > ctrl_rpv) required to conclude.
        kill_switch_threshold: P(trt_rpv < ratio × ctrl_rpv) required to kill.
        kill_switch_rpv_ratio: RPV underperformance multiplier (default 0.90).

    Returns:
        ExperimentStats with posterior point estimates and decision flags.
    """
    # Average order values — fall back to 1.0 to avoid division by zero
    ctrl_aov = (control_revenue / control_orders) if control_orders > 0 else 1.0
    trt_aov = (treatment_revenue / treatment_orders) if treatment_orders > 0 else 1.0

    # Gamma-Poisson posterior parameters.
    # treatment_days is floored at 1.0 so that a freshly-started experiment
    # (treatment_days ≈ 0) doesn't let the Gamma prior dominate and produce
    # spuriously high treatment RPV estimates.
    ctrl_alpha = _GAMMA_PRIOR_ALPHA + control_orders
    ctrl_beta = _GAMMA_PRIOR_BETA + max(control_days, 0.01)
    trt_alpha = _GAMMA_PRIOR_ALPHA + treatment_orders
    trt_beta = _GAMMA_PRIOR_BETA + max(treatment_days, 1.0)

    samples_ctrl, samples_trt = _sample_posterior_rpv(
        ctrl_alpha, ctrl_beta, ctrl_aov,
        trt_alpha, trt_beta, trt_aov,
    )

    prob_better = float((samples_trt > samples_ctrl).mean())
    prob_kill = float((samples_trt < kill_switch_rpv_ratio * samples_ctrl).mean())

    return ExperimentStats(
        experiment_id=experiment_id,
        control_n=control_orders,
        treatment_n=treatment_orders,
        control_conversions=control_orders,
        treatment_conversions=treatment_orders,
        control_rpv=round(float(samples_ctrl.mean()), 4),
        treatment_rpv=round(float(samples_trt.mean()), 4),
        prob_treatment_better=round(prob_better, 4),
        prob_kill_switch=round(prob_kill, 4),
        significance_reached=prob_better >= significance_threshold and days_running >= 3,
        kill_switch_triggered=prob_kill >= kill_switch_threshold and days_running >= 3,
        days_running=days_running,
    )


def _sample_posterior_rpv(
    ctrl_alpha: float,
    ctrl_beta: float,
    ctrl_aov: float,
    trt_alpha: float,
    trt_beta: float,
    trt_aov: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Draw samples from the Gamma-Poisson posterior RPV distributions.

    Uses PyMC when available (Linux/Docker); falls back to numpy on
    environments where PyMC cannot be imported (Windows dev, CI).
    The maths are identical: Gamma(alpha, rate=beta) × aov.
    """
    if _HAS_PYMC:
        with pm.Model():  # type: ignore[union-attr]
            lambda_ctrl = pm.Gamma("lambda_ctrl", alpha=ctrl_alpha, beta=ctrl_beta)
            lambda_trt = pm.Gamma("lambda_trt", alpha=trt_alpha, beta=trt_beta)
            pm.Deterministic("rpv_ctrl", lambda_ctrl * ctrl_aov)
            pm.Deterministic("rpv_trt", lambda_trt * trt_aov)
            prior = pm.sample_prior_predictive(samples=_N_SAMPLES, random_seed=_RNG_SEED)
        s_ctrl = prior.prior["rpv_ctrl"].values.flatten()
        s_trt = prior.prior["rpv_trt"].values.flatten()
    else:
        rng = np.random.default_rng(_RNG_SEED)
        # NumPy uses scale = 1/rate — convert beta (rate) to scale
        s_ctrl = rng.gamma(ctrl_alpha, 1.0 / ctrl_beta, _N_SAMPLES) * ctrl_aov
        s_trt = rng.gamma(trt_alpha, 1.0 / trt_beta, _N_SAMPLES) * trt_aov
    return s_ctrl, s_trt


def check_kill_switch(stats: ExperimentStats, threshold: float = 0.80) -> bool:
    """Returns True if P(trt_rpv < 0.9 × ctrl_rpv) > threshold."""
    return stats.prob_kill_switch > threshold


def check_significance(stats: ExperimentStats, threshold: float = 0.95) -> bool:
    """Returns True if P(trt_rpv > ctrl_rpv) > threshold."""
    return stats.prob_treatment_better > threshold


def compute_experiment_stats_from_data(
    experiment_id: int,
    data: dict[str, Any],
) -> ExperimentStats:
    """
    Convenience wrapper that unpacks a data dict from the DB query result.
    Expected keys: control_orders, control_days, treatment_orders,
                   treatment_days, control_revenue, treatment_revenue, days_running.
    """
    return compute_experiment_stats(
        experiment_id=experiment_id,
        control_orders=int(data.get("control_orders", 0)),
        control_days=float(data.get("control_days", 14.0)),
        treatment_orders=int(data.get("treatment_orders", 0)),
        treatment_days=float(data.get("treatment_days", 1.0)),
        control_revenue=float(data.get("control_revenue", 0.0)),
        treatment_revenue=float(data.get("treatment_revenue", 0.0)),
        days_running=int(data.get("days_running", 0)),
    )
