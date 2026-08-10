"""Multi-currency portfolios.

A foreign holding earns two returns at once: the instrument's, and the
currency's. Both belong in the reported number for a base-currency holder, and
neither is a cash flow.
"""
import pandas as pd
import pytest

from analytics.performance import PerformanceCalculator
from analytics.timeseries import PortfolioTimeSeries
from domain.portfolio import Portfolio
from domain.transaction import Transaction

from conftest import FakeFetcher


def build(transactions, fetcher, base="USD", end_date="2024-03-29"):
    portfolio = Portfolio("test", base, creation_date="2024-01-01")
    for txn in transactions:
        portfolio.add_transaction(txn)
    return PortfolioTimeSeries(portfolio, fetcher=fetcher, end_date=end_date)


def test_foreign_holding_is_converted_to_base():
    """100 lira at 0.05 USD/TRY is 5 dollars, not 100."""
    fetcher = FakeFetcher({"THYAO.IS": {"2024-01-01": 100.0}}, fx={("TRY", "USD"): 0.05})
    ts = build([Transaction("thyao.is", "2024-01-02", "BUY", 10, 100, 0, "TRY")], fetcher)

    assert ts.portfolio_value().iloc[-1] == pytest.approx(10 * 100 * 0.05)


def test_purchase_cost_is_converted_at_the_trade_date():
    """Value and flow must land on the same basis, in base currency."""
    fetcher = FakeFetcher({"THYAO.IS": {"2024-01-01": 100.0}}, fx={("TRY", "USD"): 0.05})
    ts = build([Transaction("thyao.is", "2024-01-02", "BUY", 10, 100, 0, "TRY")], fetcher)

    _, flows = ts.build_cash_and_flows()
    day = pd.Timestamp("2024-01-02")
    assert flows.loc[day] == pytest.approx(50.0)
    assert ts.portfolio_value().loc[day] == pytest.approx(flows.loc[day])
    assert ts.portfolio_returns().abs().max() < 1e-9


def test_currency_moves_are_return_not_flow():
    """Lira halves against the dollar; the instrument did not move."""
    fetcher = FakeFetcher(
        {"THYAO.IS": {"2024-01-01": 100.0}},
        fx={("TRY", "USD"): {"2024-01-01": 0.05, "2024-02-01": 0.025}},
    )
    ts = build([Transaction("thyao.is", "2024-01-02", "BUY", 10, 100, 0, "TRY")], fetcher)

    perf = PerformanceCalculator(ts.portfolio_value(), ts.portfolio_returns())
    assert perf.total_return() == pytest.approx(-0.50, abs=1e-9), "FX move missing from return"

    _, flows = ts.build_cash_and_flows()
    assert flows.loc[pd.Timestamp("2024-02-01")] == 0.0, "FX move counted as a flow"


def test_mixed_currency_portfolio_sums_in_base():
    fetcher = FakeFetcher(
        {"MSFT": {"2024-01-01": 400.0}, "THYAO.IS": {"2024-01-01": 100.0}},
        fx={("TRY", "USD"): 0.05},
    )
    ts = build(
        [
            Transaction("msft", "2024-01-02", "BUY", 1, 400, 0, "USD"),
            Transaction("thyao.is", "2024-01-02", "BUY", 10, 100, 0, "TRY"),
        ],
        fetcher,
    )

    assert ts.portfolio_value().iloc[-1] == pytest.approx(400 + 50)


def test_base_currency_holdings_need_no_rate():
    """A single-currency portfolio must not require any FX lookup at all."""
    fetcher = FakeFetcher({"MSFT": {"2024-01-01": 400.0}})       # no fx table
    ts = build([Transaction("msft", "2024-01-02", "BUY", 1, 400, 0, "USD")], fetcher)

    assert (ts.build_fx_frames() == 1.0).all().all()
    assert ts.portfolio_value().iloc[-1] == pytest.approx(400)


def test_dividends_are_converted():
    fetcher = FakeFetcher(
        {"THYAO.IS": {"2024-01-01": 100.0}},
        dividends={"THYAO.IS": {"2024-02-01": 2.0}},            # 2 lira per share
        fx={("TRY", "USD"): 0.05},
    )
    ts = build([Transaction("thyao.is", "2024-01-02", "BUY", 10, 100, 0, "TRY")], fetcher)

    cash, _ = ts.build_cash_and_flows()
    assert cash.iloc[-1] == pytest.approx(10 * 2.0 * 0.05)


def test_a_position_cannot_mix_currencies():
    """Two currencies on one ticker is a data error, not something to average."""
    fetcher = FakeFetcher({"MSFT": {"2024-01-01": 400.0}}, fx={("EUR", "USD"): 1.1})
    ts = build(
        [
            Transaction("msft", "2024-01-02", "BUY", 1, 400, 0, "USD"),
            Transaction("msft", "2024-02-01", "BUY", 1, 380, 0, "EUR"),
        ],
        fetcher,
    )

    with pytest.raises(ValueError, match="more than one currency"):
        ts.instrument_currencies


def test_missing_rate_is_reported_not_guessed():
    fetcher = FakeFetcher({"THYAO.IS": {"2024-01-01": 100.0}})    # no fx table
    ts = build([Transaction("thyao.is", "2024-01-02", "BUY", 10, 100, 0, "TRY")], fetcher)

    with pytest.raises(ValueError, match="TRY"):
        ts.portfolio_value()
