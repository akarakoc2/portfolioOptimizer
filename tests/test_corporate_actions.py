"""Splits and dividends.

yfinance always returns split-adjusted prices, so a recorded quantity is on a
stale share basis after a split. Dividends are income: they raise value without
an accompanying flow, so they must show up as return.
"""
import pandas as pd
import pytest

from analytics.performance import PerformanceCalculator
from analytics.timeseries import PortfolioTimeSeries
from domain.portfolio import Portfolio
from domain.transaction import Transaction

from conftest import FakeFetcher


def build(transactions, fetcher, end_date="2024-03-29"):
    portfolio = Portfolio("test", "USD", creation_date="2024-01-01")
    for txn in transactions:
        portfolio.add_transaction(txn)
    return PortfolioTimeSeries(portfolio, fetcher=fetcher, end_date=end_date)


# ── splits ────────────────────────────────────────────────────────────

def split_fetcher():
    """A 2-for-1 on 2024-02-01, priced the way yfinance actually reports it.

    Split-adjusted series do not step down on the split date -- the whole
    history is restated onto the post-split basis, so the series is flat at 50
    while the price that traded before the split was 100.
    """
    return FakeFetcher(
        {"AAPL": {"2024-01-01": 50.0}},
        splits={"AAPL": {"2024-02-01": 2.0}},
    )


# Bought before the split, recorded at the 100 that was actually paid.
PRE_SPLIT_BUY = Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD")


def test_quantity_is_rebased_to_current_shares():
    ts = build([PRE_SPLIT_BUY], split_fetcher())

    holdings = ts.build_holding_frames()
    assert holdings.loc[pd.Timestamp("2024-01-02"), "AAPL"] == 20, "pre-split quantity not rebased"


def test_a_split_is_not_a_return():
    """20 rebased shares at the flat adjusted 50 is the 1000 that was spent."""
    ts = build([PRE_SPLIT_BUY], split_fetcher())

    value = ts.portfolio_value()
    assert value.loc[pd.Timestamp("2024-01-31")] == pytest.approx(1000)
    assert value.loc[pd.Timestamp("2024-02-01")] == pytest.approx(1000)
    assert ts.portfolio_returns().abs().max() < 1e-9, "a split registered as a return"


def test_value_matches_cash_spent_on_the_purchase_day():
    """The basis mismatch this whole change is about: V and F must agree.

    Without rebasing, 10 recorded shares at the adjusted 50 values a 1000
    purchase at 500 and books a -50% first day.
    """
    ts = build([PRE_SPLIT_BUY], split_fetcher())

    _, flows = ts.build_cash_and_flows()
    day = pd.Timestamp("2024-01-02")
    assert ts.portfolio_value().loc[day] == pytest.approx(flows.loc[day])


def test_a_purchase_after_the_split_is_not_rebased():
    ts = build(
        [PRE_SPLIT_BUY, Transaction("aapl", "2024-03-01", "BUY", 5, 50, 0, "USD")],
        split_fetcher(),
    )

    holdings = ts.build_holding_frames()
    assert holdings.loc[pd.Timestamp("2024-03-01"), "AAPL"] == 25    # 20 rebased + 5 as recorded


# ── dividends ─────────────────────────────────────────────────────────

def dividend_fetcher():
    return FakeFetcher(
        {"AAPL": {"2024-01-01": 100.0}},                       # flat prices
        dividends={"AAPL": {"2024-02-01": 1.0}},               # 1.00 per share
    )


def test_dividends_are_income():
    """Flat prices plus a dividend is a gain, not a wash."""
    ts = build([Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD")], dividend_fetcher())

    total = PerformanceCalculator(ts.portfolio_value(), ts.portfolio_returns()).total_return()
    assert total == pytest.approx(10 / 1000, abs=1e-9), "dividend did not reach the return"


def test_dividends_are_not_an_external_flow():
    """Income is earned, not contributed -- it must not be stripped out."""
    ts = build([Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD")], dividend_fetcher())

    _, flows = ts.build_cash_and_flows()
    assert flows.loc[pd.Timestamp("2024-02-01")] == 0.0
    assert len(ts.external_cashflows) == 1                       # the initial funding only


def test_dividends_land_in_cash_and_lift_value():
    ts = build([Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD")], dividend_fetcher())

    cash, _ = ts.build_cash_and_flows()
    assert cash.loc[pd.Timestamp("2024-01-31")] == pytest.approx(0)
    assert cash.loc[pd.Timestamp("2024-02-01")] == pytest.approx(10)
    assert ts.portfolio_value().iloc[-1] == pytest.approx(1010)


def test_buying_on_the_ex_date_earns_nothing():
    """Entitlement needs holdings from the day before."""
    ts = build([Transaction("aapl", "2024-02-01", "BUY", 10, 100, 0, "USD")], dividend_fetcher())

    cash, _ = ts.build_cash_and_flows()
    assert cash.loc[pd.Timestamp("2024-02-01")] == pytest.approx(0)


def test_dividends_fund_a_later_purchase():
    """Cash on hand reduces the deposit the next buy needs."""
    ts = build(
        [
            Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("aapl", "2024-03-01", "BUY", 1, 100, 0, "USD"),
        ],
        dividend_fetcher(),
    )

    _, flows = ts.build_cash_and_flows()
    # 100 of stock against 10 of dividend cash already sitting there.
    assert flows.loc[pd.Timestamp("2024-03-01")] == pytest.approx(90)
