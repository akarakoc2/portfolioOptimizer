"""Allocation, diversification and the optimisers.

Built on synthetic returns with known correlation, so the answers are checkable
by hand rather than by eyeball.
"""
import numpy as np
import pandas as pd
import pytest

from analytics.allocation import (
    compare_allocations,
    concentration_bets,
    correlation,
    covariance,
    effective_bets,
    efficient_frontier,
    max_sharpe_weights,
    min_variance_weights,
    portfolio_volatility,
    risk_contributions,
    risk_parity_weights,
)


def returns_frame(correl, vols, days=1000, seed=0):
    """Draw `days` of returns with a known correlation and per-asset volatility."""
    rng = np.random.default_rng(seed)
    count = len(vols)
    target = np.full((count, count), correl)
    np.fill_diagonal(target, 1.0)

    draws = rng.multivariate_normal(np.zeros(count), target, size=days)
    daily = np.asarray(vols) / np.sqrt(252)
    return pd.DataFrame(draws * daily, columns=[f"A{i}" for i in range(count)])


@pytest.fixture
def independent():
    return returns_frame(0.0, [0.20] * 4)


@pytest.fixture
def herded():
    return returns_frame(0.9, [0.20] * 4)


# ── diversification ───────────────────────────────────────────────────

def test_concentration_counts_positions_not_bets(independent):
    equal = pd.Series(0.25, index=independent.columns)
    assert concentration_bets(equal) == pytest.approx(4.0)

    lopsided = pd.Series([0.85, 0.05, 0.05, 0.05], index=independent.columns)
    assert concentration_bets(lopsided) < 1.5


def test_effective_bets_sees_through_correlation(independent, herded):
    equal_ind = pd.Series(0.25, index=independent.columns)
    equal_herd = pd.Series(0.25, index=herded.columns)

    spread = effective_bets(equal_ind, covariance(independent))
    together = effective_bets(equal_herd, covariance(herded))

    assert spread > 3.0, "four independent holdings should be nearly four bets"
    assert together < 1.5, "four holdings moving as one are one bet"


def test_weights_alone_cannot_tell_them_apart(independent, herded):
    """Both look like 4 positions. Only the correlation-aware measure disagrees."""
    equal = pd.Series(0.25, index=independent.columns)
    assert concentration_bets(equal) == pytest.approx(concentration_bets(equal))
    assert effective_bets(equal, covariance(independent)) > \
           effective_bets(equal, covariance(herded))


def test_risk_contributions_sum_to_one(independent):
    weights = pd.Series([0.4, 0.3, 0.2, 0.1], index=independent.columns)
    contributions = risk_contributions(weights, covariance(independent))
    assert contributions.sum() == pytest.approx(1.0)


def test_a_volatile_sliver_carries_more_risk_than_weight():
    """6% of the money can be far more than 6% of the risk."""
    frame = returns_frame(0.0, [0.10, 0.10, 0.10, 0.80])
    weights = pd.Series([0.32, 0.31, 0.31, 0.06], index=frame.columns)

    contributions = risk_contributions(weights, covariance(frame))
    assert contributions["A3"] > 0.20, "the volatile holding's risk share is understated by weight"


# ── optimisers ────────────────────────────────────────────────────────

def test_min_variance_beats_equal_weight_on_volatility():
    frame = returns_frame(0.1, [0.10, 0.20, 0.30, 0.40])
    cov = covariance(frame)

    equal = pd.Series(0.25, index=frame.columns)
    optimal = min_variance_weights(cov, max_weight=1.0)

    assert portfolio_volatility(optimal, cov) < portfolio_volatility(equal, cov)
    assert optimal.sum() == pytest.approx(1.0)
    assert (optimal >= -1e-9).all(), "long-only"


def test_min_variance_prefers_the_quiet_asset():
    frame = returns_frame(0.0, [0.05, 0.50])
    weights = min_variance_weights(covariance(frame), max_weight=1.0)
    assert weights.iloc[0] > weights.iloc[1]


def test_max_weight_is_respected():
    frame = returns_frame(0.0, [0.05, 0.50, 0.50, 0.50])
    weights = min_variance_weights(covariance(frame), max_weight=0.30)
    assert weights.max() <= 0.30 + 1e-6


def test_risk_parity_equalises_risk_not_money():
    frame = returns_frame(0.0, [0.10, 0.20, 0.40])
    cov = covariance(frame)
    weights = risk_parity_weights(cov, max_weight=1.0)

    contributions = risk_contributions(weights, cov)
    assert contributions.max() - contributions.min() < 0.05, "risk shares not equalised"
    assert weights.iloc[0] > weights.iloc[2], "quiet asset should take more of the money"


def test_max_sharpe_leans_towards_the_better_payer():
    frame = returns_frame(0.0, [0.20, 0.20])
    cov = covariance(frame)
    mu = pd.Series([0.02, 0.15], index=frame.columns)

    weights = max_sharpe_weights(mu, cov, max_weight=1.0)
    assert weights.iloc[1] > weights.iloc[0]


def test_frontier_rises_and_is_ordered():
    frame = returns_frame(0.1, [0.15, 0.25, 0.35])
    mu = pd.Series([0.05, 0.09, 0.13], index=frame.columns)

    frontier = efficient_frontier(mu, covariance(frame), points=10, max_weight=1.0)

    assert len(frontier) > 3
    assert frontier["expected_return"].is_monotonic_increasing
    assert frontier["volatility"].iloc[-1] > frontier["volatility"].iloc[0]


def test_compare_allocations_puts_candidates_side_by_side():
    frame = returns_frame(0.1, [0.10, 0.20, 0.30])
    cov = covariance(frame)
    mu = pd.Series([0.04, 0.08, 0.12], index=frame.columns)

    table = compare_allocations(
        {
            "current": pd.Series([0.6, 0.3, 0.1], index=frame.columns),
            "min variance": min_variance_weights(cov, max_weight=1.0),
        },
        mu, cov,
    )

    assert list(table.index) == ["current", "min variance"]
    assert {"expected_return", "volatility", "effective_bets"} <= set(table.columns)
    assert table.loc["min variance", "volatility"] < table.loc["current", "volatility"]


def test_correlation_recovers_what_was_planted(herded):
    corr = correlation(herded)
    off_diagonal = corr.to_numpy()[np.triu_indices(len(corr), k=1)]
    assert off_diagonal.mean() == pytest.approx(0.9, abs=0.05)
