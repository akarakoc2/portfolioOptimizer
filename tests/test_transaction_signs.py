"""Signs and fees on a single transaction.

The regression that started all this: a SELL was recorded as a second purchase,
so every IRR on a portfolio with a sale was wrong.
"""
import pytest

from domain.transaction import Transaction


def test_buy_cost_includes_fees():
    buy = Transaction("aapl", "2024-01-02", "BUY", 10, 100, 1, "USD")
    assert buy.total_cost == 1001
    assert buy.cash_flow == -1001


def test_sell_proceeds_are_positive_and_net_of_fees():
    sell = Transaction("aapl", "2024-02-02", "SELL", 5, 200, 1, "USD")
    assert sell.total_cost == 999
    assert sell.cash_flow == 999


def test_fees_are_a_cost_in_both_directions():
    """The original bug negated the whole expression, crediting the fee on a sale."""
    gross = 5 * 200
    with_fee = Transaction("aapl", "2024-02-02", "SELL", 5, 200, 1, "USD")
    free = Transaction("aapl", "2024-02-02", "SELL", 5, 200, 0, "USD")

    assert with_fee.cash_flow < free.cash_flow
    assert free.cash_flow == gross


def test_zero_fee_round_trip_is_sign_symmetric():
    buy = Transaction("aapl", "2024-01-02", "BUY", 4, 50, 0, "USD")
    sell = Transaction("aapl", "2024-02-02", "SELL", 4, 50, 0, "USD")
    assert buy.cash_flow == -sell.cash_flow


def test_transaction_type_is_validated_at_construction():
    with pytest.raises(ValueError):
        Transaction("aapl", "2024-01-02", "GIFT", 1, 100, 0, "USD")
