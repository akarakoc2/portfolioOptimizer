"""investing.com holdings import.

The fixture is synthetic but mirrors the real export's shape: three stacked
sections with different column counts, Reuters-style symbols, currency markers
on the money columns, and a handful of rows that must be rejected by name
rather than silently dropped.
"""
import os

import pytest

from data.investing_csv import (
    ImportReport,
    build_portfolio,
    parse_date,
    parse_money,
    read_transactions,
    split_sections,
    to_yahoo_symbol,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "investing_holdings.csv")


# ── field parsing ─────────────────────────────────────────────────────

@pytest.mark.parametrize("symbol,exchange,expected", [
    ("MSFT.O", "NASDAQ", "MSFT"),
    ("ROBO.K", "NYSE", "ROBO"),
    ("THYAO.IS", "IS", "THYAO.IS"),      # Yahoo uses the same country suffix
    ("V", "NYSE", "V"),
    ("BASFn", "ETR", "BAS.DE"),          # override, not a suffix rule
])
def test_symbol_translation(symbol, exchange, expected):
    assert to_yahoo_symbol(symbol, exchange) == expected


@pytest.mark.parametrize("raw,amount,currency", [
    ("$1,002.76", 1002.76, "USD"),
    ("₺33,072.00", 33072.00, "TRY"),
    ("-$25.15", -25.15, "USD"),
    ("$0.00", 0.0, "USD"),
    ("--", None, None),
    ("-", None, None),
])
def test_money_parsing(raw, amount, currency):
    assert parse_money(raw) == (amount, currency)


@pytest.mark.parametrize("raw,expected", [
    ("05/26/2026", "2026-05-26"),        # day > 12 settles MM/DD/YYYY
    ("01/20/2026", "2026-01-20"),
    ("31/02/2026", None),                # month 31 does not exist
    ("--", None),
    ("2026-01-20", None),                # not the format this export uses
])
def test_date_parsing(raw, expected):
    assert parse_date(raw) == expected


# ── sectioning ────────────────────────────────────────────────────────

def test_sections_are_split_on_single_cell_rows():
    import csv
    rows = list(csv.reader(open(FIXTURE, encoding="utf-8-sig")))
    sections = split_sections(rows)

    assert set(sections) >= {"Open Positions Summary", "Open Positions", "Closed Positions"}
    assert len(sections["Open Positions"]["rows"]) == 4


# ── ledger reconstruction ─────────────────────────────────────────────

def test_open_lots_become_buys():
    report = read_transactions(FIXTURE, include_closed=False)

    assert len(report.transactions) == 4
    assert {t.transaction_type for t in report.transactions} == {"BUY"}
    msft = [t for t in report.transactions if t.ticker == "MSFT"]
    assert len(msft) == 2, "each lot is its own transaction"
    assert sum(t.quantity for t in msft) == 3.0


def test_closed_lots_become_a_buy_and_a_sell():
    report = read_transactions(FIXTURE)

    aapl = sorted([t for t in report.transactions if t.ticker == "AAPL"],
                  key=lambda t: t.transaction_date)
    assert [t.transaction_type for t in aapl] == ["BUY", "SELL"]
    assert aapl[0].transaction_date == "2026-01-05"
    assert aapl[1].transaction_date == "2026-03-10"
    assert aapl[1].cost_per_unit == 220.0


def test_currency_is_read_from_the_money_marker():
    report = read_transactions(FIXTURE, include_closed=False)
    by_ticker = {t.ticker: t for t in report.transactions}

    assert by_ticker["MSFT"].currency == "USD"
    assert by_ticker["THYAO.IS"].currency == "TRY"


def test_commission_becomes_fees():
    report = read_transactions(FIXTURE, include_closed=False)
    msft = [t for t in report.transactions if t.ticker == "MSFT"][0]
    assert msft.fees == 1.50


def test_transactions_come_out_chronological():
    report = read_transactions(FIXTURE)
    dates = [t.transaction_date for t in report.transactions]
    assert dates == sorted(dates)


# ── bad rows ──────────────────────────────────────────────────────────

def test_bad_rows_are_rejected_by_name_not_dropped():
    report = read_transactions(FIXTURE)

    reasons = " ".join(reason for _, reason, _ in report.rejected)
    assert "BAD.O" in reasons, "unparseable date not reported"
    assert "NEG.O" in reasons, "negative quantity not reported"
    assert "REV.O" in reasons, "close-before-open not reported"
    assert not report.ok


def test_unsupported_symbols_warn_rather_than_reject():
    report = read_transactions(FIXTURE)

    assert any("LP68048229" in w for w in report.warnings)
    assert not any(t.ticker == "LP68048229" for t in report.transactions)


def test_good_rows_survive_bad_ones():
    """One broken line must not cost the rest of the file."""
    report = read_transactions(FIXTURE)

    tickers = {t.ticker for t in report.transactions}
    assert {"MSFT", "THYAO.IS", "ROBO", "AAPL", "BAS.DE"} <= tickers
    assert len(report.rejected) == 3


def test_report_summary_names_line_numbers():
    report = read_transactions(FIXTURE)
    text = report.summary()
    assert "rejected line" in text
    assert "transactions parsed" in text


# ── portfolio assembly ────────────────────────────────────────────────

def test_build_portfolio_groups_lots_into_positions():
    portfolio, report = build_portfolio(FIXTURE, base_currency="USD")

    positions = {p.ticker: p for p in portfolio.all_positions()}
    assert positions["MSFT"].net_quantity == 3.0
    assert positions["AAPL"].net_quantity == 0.0, "closed position nets to zero"
    assert "AAPL" not in {p.ticker for p in portfolio.open_positions()}


def test_open_positions_match_the_export():
    """BAS.DE appears only in the closed section, so it must not be open."""
    portfolio, _ = build_portfolio(FIXTURE, base_currency="USD")
    assert {p.ticker for p in portfolio.open_positions()} == {"MSFT", "THYAO.IS", "ROBO"}


def test_section_footers_are_not_data():
    """'Closed P/L','$130.00' and friends are structure, not failed rows."""
    report = read_transactions(FIXTURE)
    reasons = " ".join(reason for _, reason, _ in report.rejected)
    assert "columns" not in reasons


def test_inception_defaults_to_the_earliest_transaction():
    portfolio, _ = build_portfolio(FIXTURE)
    assert portfolio.creation_date == "2026-01-05"


def test_holdings_only_import_skips_closed_positions():
    portfolio, _ = build_portfolio(FIXTURE, include_closed=False)
    assert "AAPL" not in {p.ticker for p in portfolio.all_positions()}


@pytest.mark.parametrize("symbol,expected", [
    ("MSFT", "USD"),
    ("THYAO.IS", "TRY"),
    ("BAS.DE", "EUR"),
    ("VOD.L", "GBP"),
])
def test_currency_inferred_from_listing(symbol, expected):
    """Closed rows carry no currency symbol, so the venue has to say."""
    from data.investing_csv import currency_for_symbol
    assert currency_for_symbol(symbol) == expected


def test_german_listing_is_not_assumed_to_be_dollars():
    report = read_transactions(FIXTURE)
    basf = [t for t in report.transactions if t.ticker == "BAS.DE"]
    assert basf and all(t.currency == "EUR" for t in basf)
