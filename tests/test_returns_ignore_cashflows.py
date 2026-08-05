"""The central property: funding the account is not performance.

Every test here holds prices flat, so the correct answer is always "no return".
Anything non-zero is a cash flow leaking into the return series.
"""
import pandas as pd
import pytest

from analytics.performance import PerformanceCalculator
from analytics.timeseries import PortfolioTimeSeries
from analytics.twr import TWRcalculator
from domain.portfolio import Portfolio
from domain.transaction import Transaction

from conftest import FakeFetcher


def build(transactions, fetcher, end_date="2024-03-29"):
    portfolio = Portfolio("test", "USD", creation_date="2024-01-01")
    for txn in transactions:
        portfolio.add_transaction(txn)
    return PortfolioTimeSeries(portfolio, fetcher=fetcher, end_date=end_date)


def test_a_second_purchase_is_not_a_return(fetcher):
    """The 2026-06-01 buy in main.py booked +10.59% on a flat-ish day."""
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 5, 100, 0, "USD"),
            Transaction("aapl", "2024-02-01", "BUY", 50, 100, 0, "USD"),
        ],
        fetcher,
    )

    returns = ts.portfolio_returns()
    assert returns.abs().max() < 1e-9, "a deposit showed up as a return"
    assert abs((1 + returns).prod() - 1) < 1e-9


def test_value_still_grows_when_you_add_money(fetcher):
    """Value must react to deposits even though return must not."""
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 5, 100, 0, "USD"),
            Transaction("aapl", "2024-02-01", "BUY", 5, 100, 0, "USD"),
        ],
        fetcher,
    )

    value = ts.portfolio_value()
    assert value.iloc[0] == pytest.approx(500)
    assert value.iloc[-1] == pytest.approx(1000)


def test_market_moves_still_register():
    """The adjustment must not flatten genuine performance."""
    fetcher = FakeFetcher({"AAPL": {"2024-01-01": 100.0, "2024-02-01": 150.0}})
    ts = build([Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD")], fetcher)

    perf = PerformanceCalculator(ts.portfolio_value(), ts.portfolio_returns())
    assert perf.total_return() == pytest.approx(0.50, abs=1e-9)


def test_rotation_between_holdings_is_not_a_cashflow(fetcher):
    """Sell AAPL, buy MSFT with the proceeds. Nothing crossed the boundary."""
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("aapl", "2024-02-01", "SELL", 10, 100, 0, "USD"),
            Transaction("msft", "2024-02-01", "BUY", 5, 200, 0, "USD"),
        ],
        fetcher,
    )

    _, flows = ts.build_cash_and_flows()
    rotation_day = pd.Timestamp("2024-02-01")
    assert flows.loc[rotation_day] == pytest.approx(0.0), "rotation counted as a deposit"
    assert ts.portfolio_returns().abs().max() < 1e-9


def test_full_liquidation_keeps_the_series_continuous(fetcher):
    """Sold to cash is worth what it sold for, not nothing."""
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("aapl", "2024-02-01", "SELL", 10, 100, 0, "USD"),
        ],
        fetcher,
    )

    value = ts.portfolio_value()
    assert value.index[-1] == pd.Timestamp("2024-03-29")
    assert value.iloc[-1] == pytest.approx(1000)
    assert (value > 0).all()


def test_fees_drag_on_performance(fetcher):
    """A fee is real money gone. Flat prices plus a fee is a small loss."""
    ts = build([Transaction("aapl", "2024-01-02", "BUY", 10, 100, 25, "USD")], fetcher)

    total = PerformanceCalculator(ts.portfolio_value(), ts.portfolio_returns()).total_return()
    assert total == pytest.approx(-25 / 1025, abs=1e-9)


def test_twr_agrees_with_total_return(fetcher):
    """They used to disagree because only one of them adjusted for flows."""
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 5, 100, 0, "USD"),
            Transaction("msft", "2024-02-01", "BUY", 3, 200, 0, "USD"),
        ],
        fetcher,
    )

    returns = ts.portfolio_returns()
    perf = PerformanceCalculator(ts.portfolio_value(), returns)
    assert TWRcalculator(returns).calculate_twr() == pytest.approx(perf.total_return())


def test_drawdown_ignores_deposits():
    """A deposit raised the value, reset the peak, and hid the drawdown."""
    fetcher = FakeFetcher(
        {"AAPL": {"2024-01-01": 100.0, "2024-02-01": 50.0}, "MSFT": {"2024-01-01": 200.0}}
    )
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("msft", "2024-03-01", "BUY", 100, 200, 0, "USD"),
        ],
        fetcher,
    )

    perf = PerformanceCalculator(ts.portfolio_value(), ts.portfolio_returns())
    assert perf.max_drawdown() == pytest.approx(-0.50, abs=1e-9)
