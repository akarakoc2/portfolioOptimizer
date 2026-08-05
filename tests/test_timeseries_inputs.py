"""Guards on the inputs that feed the value series.

Both of these used to fail silently, which is worse than failing loudly: the
numbers stayed plausible.
"""
import pandas as pd
import pytest

from analytics.timeseries import PortfolioTimeSeries
from domain.portfolio import Portfolio
from domain.transaction import Transaction

from conftest import FakeFetcher


def build(transactions, fetcher, end_date="2024-03-29"):
    portfolio = Portfolio("test", "USD", creation_date="2024-01-01")
    for txn in transactions:
        portfolio.add_transaction(txn)
    return PortfolioTimeSeries(portfolio, fetcher=fetcher, end_date=end_date)


def test_weekend_transaction_is_not_dropped(fetcher):
    """2024-01-06 is a Saturday. The position used to vanish entirely.

    The AAPL leg only exists to start the series earlier, so there are trading
    days on both sides of the weekend to assert against.
    """
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 1, 100, 0, "USD"),
            Transaction("msft", "2024-01-06", "BUY", 7, 200, 0, "USD"),
        ],
        fetcher,
    )

    holdings = ts.build_holding_frames()
    assert holdings["MSFT"].max() == 7, "weekend transaction was dropped"
    # Snapped forward to Monday, not backdated into a day it did not exist.
    assert holdings.loc[pd.Timestamp("2024-01-05"), "MSFT"] == 0
    assert holdings.loc[pd.Timestamp("2024-01-08"), "MSFT"] == 7


def test_missing_prices_raise_instead_of_valuing_at_zero(fetcher):
    """sum(skipna=True) used to price an unfetchable holding at nothing."""
    fetcher.prices.pop("MSFT")
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("msft", "2024-01-02", "BUY", 5, 200, 0, "USD"),
        ],
        fetcher,
    )

    with pytest.raises(ValueError, match="No price data"):
        ts.portfolio_value()


def test_out_of_order_entry_still_finds_the_real_start(fetcher):
    """ticker_start_dates read transactions[0], which is not sorted."""
    portfolio = Portfolio("test", "USD", creation_date="2024-01-01")
    portfolio.add_transaction(Transaction("aapl", "2024-02-01", "BUY", 1, 100, 0, "USD"))
    portfolio.add_transaction(Transaction("aapl", "2024-01-02", "BUY", 1, 100, 0, "USD"))

    ts = PortfolioTimeSeries(portfolio, fetcher=fetcher, end_date="2024-03-29")
    assert ts.ticker_start_dates["AAPL"] == pd.Timestamp("2024-01-02")


def test_external_cashflows_exclude_internal_rotation(fetcher):
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("aapl", "2024-02-01", "SELL", 10, 100, 0, "USD"),
            Transaction("msft", "2024-02-01", "BUY", 5, 200, 0, "USD"),
        ],
        fetcher,
    )

    flows = ts.external_cashflows
    assert len(flows) == 1, "only the initial funding crossed the boundary"
    assert flows[0] == (pd.Timestamp("2024-01-02"), -1000)


def test_price_frames_are_fetched_once(fetcher):
    """portfolio_value used to refetch on every call."""
    ts = build([Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD")], fetcher)

    ts.portfolio_value()
    ts.portfolio_value()
    ts.portfolio_returns()
    assert fetcher.calls.count("AAPL") == 1
