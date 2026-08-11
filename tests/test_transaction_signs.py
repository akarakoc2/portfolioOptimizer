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


def test_fully_closed_position_is_not_open():
    """Fractional lots leave a float residue, so `> 0` reported phantom holdings.

    These two quantities are chosen, not arbitrary: buying then selling both
    leaves +2.2e-16 rather than zero. A pair that cancels exactly would make
    this pass under the old `> 0` check and guard nothing.
    """
    from domain.position import Position
    pos = Position(Transaction("aaa", "2025-11-18", "BUY", 1.299965, 120.00, 0, "USD"))
    pos.add_transaction(Transaction("aaa", "2025-11-18", "BUY", 4.469165, 120.00, 0, "USD"))
    pos.add_transaction(Transaction("aaa", "2025-12-10", "SELL", 4.469165, 130.00, 0, "USD"))
    pos.add_transaction(Transaction("aaa", "2026-02-11", "SELL", 1.299965, 150.00, 0, "USD"))

    assert pos.net_quantity > 0, "residue gone -- this no longer tests anything"
    assert not pos.is_open
    assert pos.average_cost_basis == 0.0


def test_reopened_position_forgets_the_closed_lot():
    """A lot closed in 2025 must not drag the basis of one reopened in 2026."""
    from domain.position import Position
    pos = Position(Transaction("bbb", "2025-04-23", "BUY", 600, 50.00, 0, "TRY"))
    pos.add_transaction(Transaction("bbb", "2025-10-03", "SELL", 600, 60.00, 0, "TRY"))
    pos.add_transaction(Transaction("bbb", "2026-02-16", "BUY", 400, 85.00, 0, "TRY"))

    assert pos.average_cost_basis == pytest.approx(85.00)


def test_partial_sale_leaves_the_average_alone():
    from domain.position import Position
    pos = Position(Transaction("aapl", "2024-01-02", "BUY", 10, 100, 0, "USD"))
    pos.add_transaction(Transaction("aapl", "2024-02-01", "BUY", 10, 200, 0, "USD"))
    pos.add_transaction(Transaction("aapl", "2024-03-01", "SELL", 5, 300, 0, "USD"))

    assert pos.average_cost_basis == pytest.approx(150.0)
    assert pos.net_quantity == 15
