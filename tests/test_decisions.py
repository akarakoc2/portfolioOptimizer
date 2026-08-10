"""Decision-quality analytics."""
import pandas as pd
import pytest

from analytics.decisions import (
    cashflow_matched_benchmark,
    realisation_asymmetry,
    sale_opportunity_cost,
)
from analytics.timeseries import PortfolioTimeSeries
from domain.portfolio import Portfolio
from domain.transaction import Transaction

from conftest import FakeFetcher


def build(transactions, fetcher, base="USD", end_date="2024-03-29"):
    portfolio = Portfolio("test", base, creation_date="2024-01-01")
    for txn in transactions:
        portfolio.add_transaction(txn)
    return portfolio, PortfolioTimeSeries(portfolio, fetcher=fetcher, end_date=end_date)


# ── cash-flow-matched benchmark ───────────────────────────────────────

def test_matching_the_benchmark_exactly_adds_nothing():
    """Hold something that tracks the benchmark; active value added is zero."""
    fetcher = FakeFetcher({
        "SPY": {"2024-01-01": 100.0, "2024-03-01": 120.0},
        "CLONE": {"2024-01-01": 100.0, "2024-03-01": 120.0},
    })
    _, ts = build([Transaction("clone", "2024-01-02", "BUY", 10, 100, 0, "USD")], fetcher)

    result = cashflow_matched_benchmark(ts, "SPY", fetcher=fetcher)
    assert result["active_value_added"] == pytest.approx(0.0, abs=1e-6)


def test_beating_the_benchmark_shows_as_value_added():
    fetcher = FakeFetcher({
        "SPY": {"2024-01-01": 100.0},                       # flat
        "WINNER": {"2024-01-01": 100.0, "2024-03-01": 150.0},
    })
    _, ts = build([Transaction("winner", "2024-01-02", "BUY", 10, 100, 0, "USD")], fetcher)

    result = cashflow_matched_benchmark(ts, "SPY", fetcher=fetcher)
    assert result["active_value_added"] == pytest.approx(500.0, abs=1e-6)
    assert result["benchmark_gain"] == pytest.approx(0.0, abs=1e-9)


def test_only_external_money_reaches_the_benchmark():
    """A sale funding a purchase is not new capital, so SPY must not receive it.

    This is the objection the metric has to survive: irregular inflows, with
    some purchases paid for out of proceeds rather than fresh money.
    """
    fetcher = FakeFetcher({
        "SPY": {"2024-01-01": 100.0},
        "AAA": {"2024-01-01": 100.0},
        "BBB": {"2024-01-01": 100.0},
    })
    _, ts = build(
        [
            Transaction("aaa", "2024-01-02", "BUY", 10, 100, 0, "USD"),   # 1000 in
            Transaction("aaa", "2024-02-01", "SELL", 10, 100, 0, "USD"),  # rotation
            Transaction("bbb", "2024-02-01", "BUY", 10, 100, 0, "USD"),
        ],
        fetcher,
    )

    result = cashflow_matched_benchmark(ts, "SPY", fetcher=fetcher)
    assert result["contributed"] == pytest.approx(1000.0), "rotation counted as a contribution"


def test_later_contributions_buy_fewer_units_after_a_rise():
    fetcher = FakeFetcher({
        "SPY": {"2024-01-01": 100.0, "2024-02-01": 200.0},
        "AAA": {"2024-01-01": 100.0},
    })
    _, ts = build(
        [
            Transaction("aaa", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("aaa", "2024-02-01", "BUY", 10, 100, 0, "USD"),
        ],
        fetcher,
    )

    result = cashflow_matched_benchmark(ts, "SPY", fetcher=fetcher)
    # 1000 at 100 plus 1000 at 200 is 15 units, worth 3000 against 2000 put in.
    assert result["benchmark_value"] == pytest.approx(3000.0, abs=1e-6)


# ── sale opportunity cost ─────────────────────────────────────────────

def test_selling_before_a_rise_shows_a_cost():
    fetcher = FakeFetcher({"AAA": {"2024-01-01": 100.0, "2024-03-01": 200.0}})
    portfolio, ts = build(
        [
            Transaction("aaa", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("aaa", "2024-02-01", "SELL", 10, 100, 0, "USD"),
        ],
        fetcher,
    )

    frame = sale_opportunity_cost(portfolio, fetcher, ts)
    assert len(frame) == 1
    assert frame.loc[0, "proceeds"] == pytest.approx(1000.0)
    assert frame.loc[0, "worth_now"] == pytest.approx(2000.0)
    assert frame.loc[0, "sale_cost"] == pytest.approx(1000.0)


def test_selling_before_a_fall_shows_a_saving():
    fetcher = FakeFetcher({"AAA": {"2024-01-01": 100.0, "2024-03-01": 50.0}})
    portfolio, ts = build(
        [
            Transaction("aaa", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("aaa", "2024-02-01", "SELL", 10, 100, 0, "USD"),
        ],
        fetcher,
    )

    assert sale_opportunity_cost(portfolio, fetcher, ts).loc[0, "sale_cost"] < 0


def test_foreign_sales_are_compared_in_base_currency():
    """A lira sale must not be measured against a dollar valuation."""
    fetcher = FakeFetcher(
        {"THYAO.IS": {"2024-01-01": 100.0}},
        fx={("TRY", "USD"): 0.05},
    )
    portfolio, ts = build(
        [
            Transaction("thyao.is", "2024-01-02", "BUY", 100, 100, 0, "TRY"),
            Transaction("thyao.is", "2024-02-01", "SELL", 100, 100, 0, "TRY"),
        ],
        fetcher,
    )

    frame = sale_opportunity_cost(portfolio, fetcher, ts)
    assert frame.loc[0, "proceeds"] == pytest.approx(500.0)     # 10,000 TRY at 0.05
    assert frame.loc[0, "sale_cost"] == pytest.approx(0.0, abs=1e-6)


def test_open_positions_are_not_counted_as_sales():
    fetcher = FakeFetcher({"AAA": {"2024-01-01": 100.0}})
    portfolio, ts = build(
        [
            Transaction("aaa", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("aaa", "2024-02-01", "SELL", 4, 100, 0, "USD"),
        ],
        fetcher,
    )

    assert sale_opportunity_cost(portfolio, fetcher, ts).empty


# ── realisation asymmetry ─────────────────────────────────────────────

def test_asymmetry_reports_gains_closed_and_losses_held():
    fetcher = FakeFetcher({
        "WIN": {"2024-01-01": 100.0},
        "LOSE": {"2024-01-01": 100.0, "2024-03-01": 70.0},
    })
    portfolio, ts = build(
        [
            Transaction("win", "2024-01-02", "BUY", 10, 100, 0, "USD"),
            Transaction("win", "2024-02-01", "SELL", 10, 130, 0, "USD"),   # gain taken
            Transaction("lose", "2024-01-02", "BUY", 10, 100, 0, "USD"),   # loss held
        ],
        fetcher,
    )

    stats = realisation_asymmetry(portfolio, ts)
    assert stats["closed_positions"] == 1
    assert stats["closed_win_rate"] == pytest.approx(1.0)
    assert stats["avg_realised_gain"] == pytest.approx(0.30)
    assert stats["open_at_loss"] == 1
    assert stats["avg_open_loss"] == pytest.approx(-0.30, abs=1e-9)
