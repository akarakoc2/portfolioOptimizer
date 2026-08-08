"""How the portfolio is actually allocated, and how it might be.

Weights say where the money is. They do not say where the *risk* is, and on a
book of correlated holdings the two are far apart: a dozen names that move
together is one bet wearing a dozen hats.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize

TRADING_DAYS = 252


# ── describing what is there ──────────────────────────────────────────

def asset_history(tickers, fetcher, base_currency="USD", currencies=None,
                  lookback_days=730, end_date=None):
    """Common-window daily returns for a set of tickers, in base currency.

    PortfolioTimeSeries.asset_returns only covers the portfolio's own window, and
    each holding's series begins when it was bought. Intersecting fourteen of
    those can leave a handful of weeks -- far too little to estimate a covariance
    from, and enough to make an optimiser produce confident nonsense.

    Covariance is a property of the assets, not of when you happened to own them,
    so this fetches a common window regardless of purchase dates.
    """
    end_date = pd.Timestamp(end_date) if end_date is not None else pd.Timestamp.today()
    start_date = end_date - pd.Timedelta(days=lookback_days)
    currencies = currencies or {}

    columns = {}
    for ticker in tickers:
        prices = fetcher.get_historical_prices(ticker, start_date, end_date)
        if prices is None or prices.empty:
            continue

        series = prices["Close"].squeeze()
        series.index = pd.DatetimeIndex(series.index)
        if series.index.tz is not None:
            series.index = series.index.tz_localize(None)

        currency = currencies.get(ticker, base_currency)
        if currency != base_currency:
            rates = fetcher.get_fx_rates(currency, base_currency, start_date, end_date)
            if rates is not None:
                rates = pd.Series(rates)
                rates.index = pd.DatetimeIndex(rates.index)
                if rates.index.tz is not None:
                    rates.index = rates.index.tz_localize(None)
                series = series * rates.reindex(series.index).ffill().bfill()

        columns[ticker] = series

    frame = pd.DataFrame(columns).sort_index()
    calendar = pd.bdate_range(frame.index.min(), frame.index.max())
    frame = frame.reindex(calendar).ffill()

    return (frame.pct_change()
                 .replace([np.inf, -np.inf], np.nan)
                 .dropna(how="any"))


def covariance(asset_returns, annualise=True):
    """Annualised covariance of asset returns."""
    cov = asset_returns.dropna().cov()
    return cov * TRADING_DAYS if annualise else cov


def correlation(asset_returns):
    return asset_returns.dropna().corr()


def portfolio_volatility(weights, cov):
    weights = np.asarray(weights, dtype=float)
    return float(np.sqrt(weights @ cov.to_numpy() @ weights))


def concentration_bets(weights):
    """Inverse Herfindahl on weights: how many positions this *looks* like.

    Blind to correlation, which is the point -- comparing it against
    effective_bets is what exposes the gap.
    """
    w = np.asarray(weights, dtype=float)
    total = w.sum()
    if total == 0:
        return float("nan")
    w = w / total
    return float(1.0 / np.sum(w ** 2))


def effective_bets(weights, cov):
    """Squared diversification ratio: how many independent bets this really is.

    The diversification ratio is the weighted average volatility divided by the
    portfolio's own volatility. Uncorrelated holdings make it large; holdings
    that move together drive it towards 1 no matter how many there are.
    """
    w = np.asarray(weights, dtype=float)
    total = w.sum()
    if total == 0:
        return float("nan")
    w = w / total

    vols = np.sqrt(np.diag(cov.to_numpy()))
    weighted_vol = float(w @ vols)
    portfolio_vol = portfolio_volatility(w, cov)

    if portfolio_vol == 0:
        return float("nan")

    return float((weighted_vol / portfolio_vol) ** 2)


def risk_contributions(weights, cov):
    """Share of portfolio volatility each position is responsible for.

    Weight and risk contribution diverge sharply for a small, volatile holding:
    6% of the money can easily be 15% of the risk.
    """
    w = np.asarray(weights, dtype=float)
    total = w.sum()
    if total == 0:
        return pd.Series(float("nan"), index=cov.index)
    w = w / total

    matrix = cov.to_numpy()
    portfolio_vol = float(np.sqrt(w @ matrix @ w))
    if portfolio_vol == 0:
        return pd.Series(float("nan"), index=cov.index)

    marginal = matrix @ w
    contribution = w * marginal / (portfolio_vol ** 2)     # sums to 1

    return pd.Series(contribution, index=cov.index)


def segment_breakdown(timeseries, segments=None):
    """Value, weight, return and volatility per segment.

    Defaults to grouping by quote currency, which for a part-Turkish book is
    the split that matters: those holdings answer to a different market and a
    different currency, and averaging them with the US book hides both.
    """
    if segments is None:
        segments = timeseries.instrument_currencies

    values = timeseries.build_value_frame()
    returns = timeseries.asset_returns()
    labels = pd.Series(segments)

    latest = values.iloc[-1]

    rows = []
    for label in sorted(set(labels.values)):
        # Only positions still held: a closed one has no value and no weight,
        # and counting it makes the segment look broader than it is.
        tickers = [t for t in values.columns
                   if segments.get(t) == label and abs(latest[t]) > 1e-9]
        if not tickers:
            continue

        segment_value = values[tickers].sum(axis=1)
        weights = values[tickers].iloc[-1]
        weights = weights / weights.sum() if weights.sum() else weights

        segment_returns = (returns[tickers] * weights).sum(axis=1, min_count=1).dropna()

        rows.append({
            "segment": label,
            "holdings": len(tickers),
            "value": float(segment_value.iloc[-1]),
            "weight": float(segment_value.iloc[-1] / values.iloc[-1].sum()),
            "total_return": float((1 + segment_returns).prod() - 1),
            "volatility": float(segment_returns.std() * np.sqrt(TRADING_DAYS)),
        })

    frame = pd.DataFrame(rows).set_index("segment")
    return frame.sort_values("weight", ascending=False)


# ── suggesting what could be there ────────────────────────────────────

def _solve(objective, count, bounds, seed=None):
    start = seed if seed is not None else np.repeat(1.0 / count, count)
    result = minimize(
        objective,
        start,
        method="SLSQP",
        bounds=[bounds] * count,
        constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}],
        options={"maxiter": 500, "ftol": 1e-10},
    )
    return result.x


def min_variance_weights(cov, max_weight=0.25):
    """Lowest-volatility long-only mix.

    Needs no return forecast, only the covariance, which is why it is the most
    trustworthy thing an optimiser here can produce. Expected returns estimated
    from 19 months of history are mostly noise; covariance is merely noisy.
    """
    matrix = cov.to_numpy()
    weights = _solve(lambda w: w @ matrix @ w, len(cov), (0.0, max_weight))
    return pd.Series(weights, index=cov.index)


def risk_parity_weights(cov, max_weight=0.25):
    """Every holding contributing the same share of risk.

    Also forecast-free. Tends to shade towards the quieter holdings, which is
    usually the honest answer to "why is one position driving everything".
    """
    matrix = cov.to_numpy()
    target = 1.0 / len(cov)

    def objective(w):
        portfolio_var = w @ matrix @ w
        if portfolio_var <= 0:
            return 1e6
        contribution = w * (matrix @ w) / portfolio_var
        return float(np.sum((contribution - target) ** 2))

    weights = _solve(objective, len(cov), (1e-4, max_weight))
    return pd.Series(weights, index=cov.index)


def max_sharpe_weights(expected_returns, cov, risk_free=0.0, max_weight=0.25):
    """Highest reward-per-unit-risk mix.

    Fragile by construction: it leans entirely on `expected_returns`, and a
    historical mean over a short window is a poor forecast. Treat the output as
    a description of what happened, not a recommendation. min_variance and
    risk_parity are the ones to act on.
    """
    matrix = cov.to_numpy()
    mu = np.asarray(expected_returns.reindex(cov.index), dtype=float)

    def objective(w):
        vol = np.sqrt(w @ matrix @ w)
        if vol <= 0:
            return 1e6
        return -((w @ mu - risk_free) / vol)

    weights = _solve(objective, len(cov), (0.0, max_weight))
    return pd.Series(weights, index=cov.index)


def efficient_frontier(expected_returns, cov, points=25, max_weight=0.25):
    """Risk and return of the best mix at each achievable return level.

    Most useful not for picking a point but for seeing where the current
    portfolio sits relative to the curve -- how much volatility is being taken
    for the return it produced.
    """
    matrix = cov.to_numpy()
    mu = np.asarray(expected_returns.reindex(cov.index), dtype=float)
    count = len(cov)

    lowest = min_variance_weights(cov, max_weight=max_weight)
    floor = float(lowest @ mu)
    ceiling = float(np.max(mu)) * 0.999

    if ceiling <= floor:
        return pd.DataFrame(columns=["volatility", "expected_return"])

    rows = []
    for target in np.linspace(floor, ceiling, points):
        result = minimize(
            lambda w: w @ matrix @ w,
            np.repeat(1.0 / count, count),
            method="SLSQP",
            bounds=[(0.0, max_weight)] * count,
            constraints=[
                {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
                {"type": "eq", "fun": lambda w, t=target: w @ mu - t},
            ],
            options={"maxiter": 500, "ftol": 1e-10},
        )
        if result.success:
            rows.append({
                "volatility": float(np.sqrt(result.x @ matrix @ result.x)),
                "expected_return": float(target),
            })

    return pd.DataFrame(rows)


def compare_allocations(allocations, expected_returns, cov):
    """Volatility, expected return and diversification for each candidate mix.

    Put the current portfolio in here alongside the optimiser's suggestions --
    the comparison is the useful part, not any single row.
    """
    mu = expected_returns.reindex(cov.index)

    rows = {}
    for name, weights in allocations.items():
        w = pd.Series(weights).reindex(cov.index).fillna(0.0)
        vol = portfolio_volatility(w, cov)
        expected = float(w @ mu)
        rows[name] = {
            "expected_return": expected,
            "volatility": vol,
            "return_per_risk": expected / vol if vol else float("nan"),
            "effective_bets": effective_bets(w, cov),
            "largest_weight": float(w.max()),
        }

    return pd.DataFrame(rows).T
