"""investing.com holdings import.

The fixture is synthetic but mirrors the real export's shape: three stacked
sections with different column counts, Reuters-style symbols, currency markers
on the money columns, and a handful of rows that must be rejected by name
rather than silently dropped.
"""
import os

import pytest

from conftest import FakeFetcher

from data.investing_csv import (
    ImportReport,
    SymbolResolver,
    build_portfolio,
    parse_date,
    parse_money,
    read_transactions,
    split_sections,
    symbol_candidates,
    to_yahoo_symbol,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "investing_holdings.csv")

# Xetra rows, as investing.com writes them for a cross-listed holding.
CROSS_LISTED = os.path.join(os.path.dirname(__file__), "fixtures", "investing_cross_listed.csv")


# ── field parsing ─────────────────────────────────────────────────────

@pytest.mark.parametrize("symbol,exchange,expected", [
    ("MSFT.O", "NASDAQ", "MSFT"),
    ("ROBO.K", "NYSE", "ROBO"),
    ("HALKB.IS", "IS", "HALKB.IS"),      # Yahoo uses the same country suffix
    ("V", "NYSE", "V"),
    ("BASFn", "ETR", "BAS.DE"),          # override, not a suffix rule
])
def test_symbol_translation(symbol, exchange, expected):
    assert to_yahoo_symbol(symbol, exchange) == expected


@pytest.mark.parametrize("raw,amount,currency", [
    ("$1,234.56", 1234.56, "USD"),
    ("₺12,345.00", 12345.00, "TRY"),
    ("-$67.89", -67.89, "USD"),
    ("$0.00", 0.0, "USD"),
    ("--", None, None),
    ("-", None, None),
])
def test_money_parsing(raw, amount, currency):
    assert parse_money(raw) == (amount, currency)


@pytest.mark.parametrize("raw,expected", [
    ("07/19/2026", "2026-07-19"),        # day > 12 settles MM/DD/YYYY
    ("01/13/2026", "2026-01-13"),
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
    assert by_ticker["HALKB.IS"].currency == "TRY"


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
    assert {"MSFT", "HALKB.IS", "ROBO", "AAPL", "BAS.DE"} <= tickers
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
    assert {p.ticker for p in portfolio.open_positions()} == {"MSFT", "HALKB.IS", "ROBO"}


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
    ("HALKB.IS", "TRY"),
    ("BAS.DE", "EUR"),
    ("VOD.L", "GBP"),
    ("WRT1V.HE", "EUR"),     # Helsinki, which used to fall through to dollars
])
def test_currency_inferred_from_listing(symbol, expected):
    """Closed rows carry no currency symbol, so the venue has to say."""
    from data.investing_csv import currency_for_symbol
    assert currency_for_symbol(symbol) == expected


def test_german_listing_is_not_assumed_to_be_dollars():
    report = read_transactions(FIXTURE)
    basf = [t for t in report.transactions if t.ticker == "BAS.DE"]
    assert basf and all(t.currency == "EUR" for t in basf)


# ── cross-listed symbols ──────────────────────────────────────────────
#
# A secondary listing has its own local ticker: Microsoft on Xetra is MSF.DE.
# Appending the venue suffix to the US ticker produces MSFT.DE, which Yahoo
# answers with YFPricesMissingError -- and only at valuation time, long after
# the import said it was fine.

@pytest.mark.parametrize("symbol,exchange,expected", [
    ("MSFT", "ETR", "MSF.DE"),           # suffix appended from the exchange
    ("MSFT.DE", "ETR", "MSF.DE"),        # suffix already on the symbol
    ("NVDA.DE", "ETR", "NVD.DE"),
    ("GOOGL.DE", "ETR", "ABEA.DE"),
    ("MSFT.O", "NASDAQ", "MSFT"),        # a US row is not a cross-listing
])
def test_xetra_rows_use_the_local_ticker(symbol, exchange, expected):
    assert to_yahoo_symbol(symbol, exchange) == expected


def test_candidates_run_stated_venue_first_primary_listing_last():
    """Order matters: the first candidate that resolves fixes the currency."""
    assert symbol_candidates("MSFT.DE", "ETR") == ["MSF.DE", "MSFT.DE", "MSFT"]
    assert symbol_candidates("BASFn", "ETR")[0] == "BAS.DE"      # override wins


def test_resolution_stops_at_the_first_candidate_with_prices():
    fetcher = FakeFetcher({"MSF.DE": {"2024-01-01": 400.0}})
    resolution = SymbolResolver(fetcher).resolve("MSFT.DE", "ETR")

    assert resolution.ticker == "MSF.DE"
    assert resolution.currency == "EUR"
    assert not resolution.venue_changed
    assert resolution.note is None


def test_a_resolved_symbol_is_not_probed_twice():
    """Validation is a network call; the resolution has to be remembered."""
    fetcher = FakeFetcher({"MSF.DE": {"2024-01-01": 400.0}})
    resolver = SymbolResolver(fetcher)

    resolver.resolve("MSFT.DE", "ETR")
    probes = list(resolver.probes)
    resolver.resolve("MSFT.DE", "ETR")

    assert resolver.probes == probes, "re-probed a symbol already resolved"


def test_failed_resolutions_are_cached_too(tmp_path):
    """A negative is the expensive probe, and the price cache cannot hold one."""
    cache = str(tmp_path / "resolutions.parquet")
    fetcher = FakeFetcher({})

    first = SymbolResolver(fetcher, cache_path=cache)
    assert not first.resolve("NOPE.DE", "ETR").ok
    assert first.probes

    second = SymbolResolver(fetcher, cache_path=cache)
    assert not second.resolve("NOPE.DE", "ETR").ok
    assert second.probes == [], "reprobed a symbol known not to resolve"


def test_seeded_mappings_need_no_probe():
    resolver = SymbolResolver()          # no provider at all
    assert resolver.resolve("MSFT.DE", "ETR").ticker == "MSF.DE"
    assert resolver.probes == []


def test_cross_listing_resolves_to_its_local_ticker():
    fetcher = FakeFetcher({"MSF.DE": {"2024-01-01": 400.0}, "FLNC": {"2024-01-01": 14.0}})
    report = read_transactions(CROSS_LISTED, resolver=SymbolResolver(fetcher))

    microsoft = [t for t in report.transactions if t.ticker == "MSF.DE"]
    assert len(microsoft) == 1
    assert microsoft[0].currency == "EUR"
    assert not any("MSFT.DE" in w for w in report.warnings)


def test_venue_fallback_warns_and_corrects_the_currency():
    """Resolving a Xetra row to the US listing moves the price into dollars."""
    fetcher = FakeFetcher({"MSF.DE": {"2024-01-01": 400.0}, "FLNC": {"2024-01-01": 14.0}})
    report = read_transactions(CROSS_LISTED, resolver=SymbolResolver(fetcher))

    fluence = [t for t in report.transactions if t.ticker == "FLNC"]
    assert len(fluence) == 1, "the Xetra row should fall back to the US listing"
    assert fluence[0].currency == "USD", "kept the row's EUR marker against a USD quote"

    warning = [w for w in report.warnings if "FLNC.DE" in w]
    assert warning, "venue fallback was silent"
    assert "USD" in warning[0] and "EUR" in warning[0]


def test_unresolvable_symbol_is_named_not_dropped():
    fetcher = FakeFetcher({"MSF.DE": {"2024-01-01": 400.0}, "FLNC": {"2024-01-01": 14.0}})
    report = read_transactions(CROSS_LISTED, resolver=SymbolResolver(fetcher))

    assert not any(t.ticker.startswith("NOPE") for t in report.transactions)

    warning = [w for w in report.warnings if "NOPE.DE" in w]
    assert warning, "unresolvable symbol vanished without a word"
    assert "NOPE" in warning[0], "the candidates tried are not in the report"


def test_import_without_a_provider_verifies_nothing():
    """Offline imports still work; they just cannot promise the ticker is live."""
    report = read_transactions(CROSS_LISTED)
    tickers = {t.ticker for t in report.transactions}

    assert "MSF.DE" in tickers, "seeded mapping should apply without a provider"
    assert "FLNC.DE" in tickers, "unverified candidate is taken at face value"
    assert report.ok
