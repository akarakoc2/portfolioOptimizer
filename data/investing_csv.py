"""Importer for investing.com holdings exports.

The export is not one table but three stacked ones with different column
counts, so a DictReader over the file will not work. Two of them carry dates,
and together they rebuild a transaction ledger:

    Open Positions    -> one BUY per lot
    Closed Positions  -> one BUY at the open date, one SELL at the close date

The third, "Open Positions Summary", is an aggregate of the second with no
dates, and is skipped.

Rows that cannot be parsed are collected in the report rather than raised, so
one bad line in a long export does not cost you the rest of it.

Symbols are a second source of failure, handled the same way. Translating an
export symbol to a Yahoo ticker is guesswork on any venue that cross-lists, so
SymbolResolver treats each translation as a candidate to be checked against the
price provider rather than as an answer -- see the notes on LOCAL_LISTINGS.
"""

import csv
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from domain.portfolio import Portfolio
from domain.transaction import Transaction

# investing.com uses Reuters-style suffixes. The exchange marker is dropped;
# the country marker is what Yahoo wants.
_SUFFIX_RULES = {
    ".O": "",       # NASDAQ
    ".K": "",       # NYSE Arca
    ".N": "",       # NYSE
    ".IS": ".IS",   # Istanbul -- Yahoo uses the same suffix
    ".L": ".L",     # London
    ".DE": ".DE",   # Xetra
    ".HE": ".HE",   # Helsinki
}

# Symbols the suffix rules cannot reach. Reuters short codes for German
# listings, mostly. Extend as you meet them.
SYMBOL_OVERRIDES = {
    "BASFn": "BAS.DE",
    "CBKG": "CBK.DE",
    "DBKGn": "DBK.DE",
    "SIEGn": "SIE.DE",
}

# Exchanges whose symbols carry no suffix at all.
_EXCHANGE_SUFFIX = {"ETR": ".DE", "IS": ".IS", "HE": ".HE"}

# A cross-listed security trades under a *local* ticker on its secondary venue,
# which has nothing to do with its primary one: Microsoft on Xetra is MSF.DE,
# not MSFT.DE. There is no rule that derives one from the other, so the frequent
# pairs are seeded here -- keyed by venue suffix, then by the bare symbol the
# export carries -- and everything else has to be probed.
#
# Every entry below was checked against the provider for company name, currency
# and exchange. A wrong entry prices the wrong security silently, which is worse
# than not having the entry at all, so add only what you have verified.
LOCAL_LISTINGS = {
    ".DE": {
        "AAPL": "APC.DE",
        "ADBE": "ADB.DE",
        "AMD": "AMD.DE",
        "AMZN": "AMZ.DE",
        "CSCO": "CIS.DE",
        "DIS": "WDP.DE",
        "GOOG": "ABEC.DE",      # class C, as GOOG is
        "GOOGL": "ABEA.DE",     # class A
        "IBM": "IBM.DE",
        "INTC": "INL.DE",
        "KO": "CCC3.DE",
        "MCD": "MDO.DE",
        "META": "FB2A.DE",
        "MSFT": "MSF.DE",
        "NFLX": "NFC.DE",
        "NVDA": "NVD.DE",
        "ORCL": "ORC.DE",
        "PYPL": "2PP.DE",
        "TSLA": "TL0.DE",
        "V": "3V64.DE",
    },
}

# Symbols with no Yahoo listing: delisted, taken private, or fund codes that
# were never there. Imported rows referencing these are reported, not silently
# dropped, because a missing position changes every number downstream.
UNSUPPORTED = {
    "LP68048229",   # Yapı Kredi Portföy Altın Fonu -- Turkish fund code
    "IAS.O",        # Integral Ad Science -- taken private, history withdrawn
}

_CURRENCY_SYMBOLS = {"$": "USD", "₺": "TRY", "€": "EUR", "£": "GBP"}

# Quote currency by Yahoo listing suffix, for rows that carry no currency
# symbol. A US listing has no suffix, hence the default.
_SUFFIX_CURRENCY = {
    ".IS": "TRY", ".DE": "EUR", ".L": "GBP", ".PA": "EUR", ".AS": "EUR",
    ".MI": "EUR", ".MC": "EUR", ".SW": "CHF", ".T": "JPY", ".TO": "CAD",
    ".AX": "AUD", ".ST": "SEK", ".OL": "NOK", ".CO": "DKK", ".WA": "PLN",
    ".HE": "EUR",
}

_NULLS = {"", "-", "--", "N/A"}


@dataclass
class ImportReport:
    """Outcome of an import: what parsed, what did not, and why."""

    transactions: list = field(default_factory=list)
    rejected: list = field(default_factory=list)      # (line_no, reason, raw row)
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.rejected

    def summary(self):
        lines = [
            f"{len(self.transactions)} transactions parsed, "
            f"{len(self.rejected)} rows rejected, {len(self.warnings)} warnings."
        ]
        for line_no, reason, _ in self.rejected:
            lines.append(f"  rejected line {line_no}: {reason}")
        for warning in self.warnings:
            lines.append(f"  warning: {warning}")
        return "\n".join(lines)


def _base_symbol(symbol):
    """Strip the Reuters venue marker, leaving the bare ticker."""
    # Longest suffix first, so '.IS' is not matched as a bare '.I'.
    for suffix in sorted(_SUFFIX_RULES, key=len, reverse=True):
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)]
    return symbol


def stated_suffix(symbol, exchange=""):
    """The Yahoo venue suffix a row claims, from its symbol or its exchange.

    '' means a US listing. This is what the row *says*, not what resolves.
    """
    symbol = symbol.strip()

    for suffix in sorted(_SUFFIX_RULES, key=len, reverse=True):
        if symbol.endswith(suffix):
            return _SUFFIX_RULES[suffix]

    return _EXCHANGE_SUFFIX.get(exchange.strip().upper(), "")


def _suffix_of(yahoo_symbol):
    """The venue suffix on a Yahoo symbol, or '' for a US listing."""
    for suffix in sorted(_SUFFIX_CURRENCY, key=len, reverse=True):
        if yahoo_symbol.endswith(suffix):
            return suffix
    return ""


def symbol_candidates(symbol, exchange=""):
    """Yahoo tickers worth trying for one export row, best first.

    Venue-consistent candidates come first, because staying on the venue the row
    names is the only answer that keeps its quote currency. The bare symbol -- the
    primary US listing of a cross-listed name -- comes last for the same reason:
    taking it moves the price into another currency, so it is worth doing only
    once nothing on the stated venue answers.
    """
    symbol = symbol.strip()
    base = _base_symbol(symbol)
    suffix = stated_suffix(symbol, exchange)

    candidates = []

    if symbol in SYMBOL_OVERRIDES:
        candidates.append(SYMBOL_OVERRIDES[symbol])

    local = LOCAL_LISTINGS.get(suffix, {}).get(base.upper())
    if local:
        candidates.append(local)

    candidates.append(base + suffix)    # what the suffix rules alone produce
    candidates.append(base)             # the primary listing, other currency

    # Uppercased so the resolution cache, the probe and the Transaction that
    # comes out of it all name the ticker the same way.
    seen = set()
    unique = [c.upper() for c in candidates
              if c and not (c.upper() in seen or seen.add(c.upper()))]

    # Never empty, so callers can index without checking. An empty symbol is
    # rejected upstream by name; it must not turn into an IndexError here.
    return unique or [symbol.upper()]


def to_yahoo_symbol(symbol, exchange=""):
    """Translate an investing.com symbol to its most likely Yahoo equivalent.

    Static translation only: the best candidate, unverified. Use SymbolResolver
    when you can afford to check it -- on a cross-listing the best candidate is
    still a guess.
    """
    return symbol_candidates(symbol, exchange)[0]


def currency_for_symbol(yahoo_symbol):
    """Quote currency implied by a Yahoo listing suffix. US listings have none."""
    return _SUFFIX_CURRENCY.get(_suffix_of(yahoo_symbol), "USD")


@dataclass(frozen=True)
class Resolution:
    """Where one export symbol landed, and what that cost.

    `ticker` is None when nothing resolved. `venue_changed` means the ticker
    trades somewhere other than the row's own venue, so `currency` -- not the
    row's currency marker -- is the one the price is quoted in.
    """

    symbol: str
    ticker: str = None
    currency: str = None
    venue_changed: bool = False
    note: str = None

    @property
    def ok(self):
        return self.ticker is not None


class SymbolResolver:
    """Turns export symbols into Yahoo tickers that actually carry prices.

    Without a fetcher this is pure translation: the best candidate wins and
    nothing is verified, which is all an offline import can honestly do. Given
    one, candidates are probed in order and the first with price history wins --
    so a cross-listing that Yahoo does not carry under its local ticker is named
    here, in the ImportReport, instead of surfacing as a YFPricesMissingError
    halfway through a valuation.

    Decisions are cached in the fetcher's cache directory, negatives included:
    a symbol that failed to resolve is the expensive one to re-probe, and it is
    exactly the one the plain price cache cannot remember.
    """

    # Long enough to clear a holiday week on any venue. A listing with no prices
    # in this window cannot be valued today either, resolved or not.
    PROBE_DAYS = 45

    CACHE_FILENAME = "symbol-resolutions.parquet"

    def __init__(self, fetcher=None, cache_path=None, probe_days=None):
        self.fetcher = fetcher
        self.probe_days = probe_days or self.PROBE_DAYS
        self.probes = []                    # tickers actually sent to the provider

        if cache_path is None:
            directory = getattr(fetcher, "cache_directory", None)
            cache_path = os.path.join(directory, self.CACHE_FILENAME) if directory else None

        self.cache_path = cache_path
        self._decisions = self._load()      # key -> ticker, '' meaning unresolvable

    # ── resolution cache ──────────────────────────────────────────────

    @staticmethod
    def _key(symbol, exchange):
        return f"{symbol.strip().upper()}@{exchange.strip().upper()}"

    def _load(self):
        if not self.cache_path or not os.path.exists(self.cache_path):
            return {}

        try:
            cached = pd.read_parquet(self.cache_path)
        except Exception as exc:
            print(f"Warning: symbol resolution cache is unreadable ({exc}). Reprobing.")
            return {}

        return {str(k): ("" if pd.isna(v) else str(v)) for k, v in cached["ticker"].items()}

    def _remember(self, key, ticker):
        self._decisions[key] = ticker

        if not self.cache_path:
            return

        # Merge against what is on disk rather than overwriting, so a second
        # importer running alongside this one does not lose its probes.
        merged = dict(self._load())
        merged.update(self._decisions)

        frame = pd.DataFrame({"ticker": pd.Series(merged, dtype="object")}).sort_index()
        frame.index.name = "symbol"

        directory = os.path.dirname(self.cache_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        frame.to_parquet(self.cache_path)

    # ── probing ───────────────────────────────────────────────────────

    def _has_prices(self, ticker):
        """True when the provider carries recent price history for `ticker`."""
        self.probes.append(ticker)

        end = datetime.now()
        start = end - timedelta(days=self.probe_days)

        try:
            prices = self.fetcher.get_historical_prices(ticker, start, end)
        except Exception:
            # yfinance signals an unknown symbol by raising as readily as by
            # returning nothing, and either way we have no evidence the ticker
            # is right. Treat both as "did not resolve" and move on.
            return False

        return prices is not None and not prices.empty

    # ── public api ────────────────────────────────────────────────────

    def resolve(self, symbol, exchange=""):
        """Resolve one export symbol to a Resolution. Never raises."""
        symbol = symbol.strip()

        if symbol in UNSUPPORTED:
            return Resolution(symbol, note=f"{symbol} has no Yahoo listing; position excluded")

        candidates = symbol_candidates(symbol, exchange)
        key = self._key(symbol, exchange)

        if key in self._decisions:
            remembered = self._decisions[key]
            return self._accept(symbol, exchange, remembered) if remembered \
                else self._unresolved(symbol, candidates)

        if self.fetcher is None:
            # Nothing to check against, so the best candidate stands unverified.
            return self._accept(symbol, exchange, candidates[0])

        for candidate in candidates:
            if self._has_prices(candidate):
                self._remember(key, candidate)
                return self._accept(symbol, exchange, candidate)

        self._remember(key, "")
        return self._unresolved(symbol, candidates)

    def _accept(self, symbol, exchange, ticker):
        currency = currency_for_symbol(ticker)
        stated = stated_suffix(symbol, exchange)

        if _suffix_of(ticker) == stated:
            return Resolution(symbol, ticker, currency)

        # Falling back off the stated venue changes the quote currency, and the
        # row's own currency marker still names the old one. Say so loudly: an
        # unnoticed swap hands the FX layer a dollar price labelled in euros.
        return Resolution(
            symbol, ticker, currency, venue_changed=True,
            note=(f"{symbol} does not resolve on {exchange.strip() or 'its stated venue'}; "
                  f"priced as {ticker} instead, quoted in {currency} rather than "
                  f"{_SUFFIX_CURRENCY.get(stated, 'USD')}"),
        )

    def _unresolved(self, symbol, candidates):
        return Resolution(symbol, note=(
            f"{symbol} resolves to no Yahoo listing (tried {', '.join(candidates)}); "
            f"position excluded"
        ))


def parse_money(raw):
    """('$1,002.76') -> (1002.76, 'USD'). The symbol is the only currency marker."""
    if raw is None or raw.strip() in _NULLS:
        return None, None

    raw = raw.strip()
    currency = next((code for sym, code in _CURRENCY_SYMBOLS.items() if sym in raw), None)

    digits = re.sub(r"[^\d.\-]", "", raw)
    if digits in {"", "-", "."}:
        return None, currency

    return float(digits), currency


def parse_number(raw):
    if raw is None or raw.strip() in _NULLS:
        return None
    digits = re.sub(r"[^\d.\-]", "", raw.strip())
    return float(digits) if digits not in {"", "-", "."} else None


def parse_date(raw):
    """investing.com writes MM/DD/YYYY ('05/26/2026' settles the ambiguity)."""
    raw = (raw or "").strip()
    if raw in _NULLS:
        return None

    match = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", raw)
    if not match:
        return None

    month, day, year = match.groups()
    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
        return None

    return f"{year}-{month}-{day}"


def split_sections(rows):
    """Break the file into {section name: (header, data rows with line numbers)}.

    Sections are announced by a row holding a single non-empty cell.
    """
    sections = {}
    current = None

    for line_no, row in enumerate(rows, start=1):
        cells = [c.strip() for c in row]

        if len([c for c in cells if c]) == 1 and len(cells) == 1:
            current = cells[0]
            sections[current] = {"header": None, "rows": []}
            continue

        if current is None or not any(cells):
            continue

        if sections[current]["header"] is None:
            sections[current]["header"] = cells
        else:
            sections[current]["rows"].append((line_no, row))

    return sections


def _index_of(header, *names):
    for name in names:
        if name in header:
            return header.index(name)
    return None


def _read_lot(line_no, row, header, report, resolver, *, closing=False):
    """Turn one lot row into one or two Transactions. Returns a list."""
    symbol = row[_index_of(header, "Symbol")].strip()
    exchange = row[_index_of(header, "Exchange")].strip()

    if not symbol:
        report.rejected.append((line_no, "no symbol", row))
        return []

    resolution = resolver.resolve(symbol, exchange)

    if resolution.note:
        report.warnings.append(f"line {line_no}: {resolution.note}")

    if not resolution.ok:
        return []

    ticker = resolution.ticker

    open_date = parse_date(row[_index_of(header, "Open Date")])
    if open_date is None:
        report.rejected.append((line_no, f"unparseable open date for {symbol}", row))
        return []

    quantity = parse_number(row[_index_of(header, "Amount")])
    if quantity is None or quantity <= 0:
        report.rejected.append((line_no, f"invalid amount for {symbol}", row))
        return []

    open_price = parse_number(row[_index_of(header, "Open Price", "Avg Price")])
    if open_price is None or open_price < 0:
        report.rejected.append((line_no, f"invalid open price for {symbol}", row))
        return []

    # Commission carries the currency marker, and is the most reliable one on
    # the row: Market Value is absent from the closed section.
    fees, currency = (None, None)
    commission_at = _index_of(header, "Commission")
    if commission_at is not None:
        fees, currency = parse_money(row[commission_at])

    if currency is None:
        value_at = _index_of(header, "Market Value")
        if value_at is not None:
            _, currency = parse_money(row[value_at])

    if currency is None:
        # Closed rows carry no money column with a currency symbol on them, so
        # infer from the listing venue -- which is what actually determines the
        # quote currency anyway.
        currency = currency_for_symbol(ticker)
        report.warnings.append(
            f"line {line_no}: no currency marker for {symbol}; "
            f"inferred {currency} from the listing"
        )

    if resolution.venue_changed:
        # The row's marker names the currency of the venue it claimed, not the
        # one we could actually price on. Keeping it would leave the FX layer
        # converting a dollar price as though it were euros.
        currency = resolution.currency

    fees = fees or 0.0

    try:
        transactions = [
            Transaction(ticker, open_date, "BUY", quantity, open_price, fees, currency)
        ]
    except ValueError as exc:
        report.rejected.append((line_no, f"{symbol}: {exc}", row))
        return []

    if not closing:
        return transactions

    close_date = parse_date(row[_index_of(header, "Close Date")])
    close_price = parse_number(row[_index_of(header, "Close Price")])

    if close_date is None or close_price is None:
        report.rejected.append((line_no, f"unparseable close for {symbol}", row))
        return []

    if close_date < open_date:
        report.rejected.append(
            (line_no, f"{symbol} closes {close_date} before it opens {open_date}", row)
        )
        return []

    try:
        # The closed section has no commission column, so sell-side fees are
        # simply unavailable in the source data.
        transactions.append(
            Transaction(ticker, close_date, "SELL", quantity, close_price, 0.0, currency)
        )
    except ValueError as exc:
        report.rejected.append((line_no, f"{symbol} close: {exc}", row))
        return []

    return transactions


def read_transactions(path, include_closed=True, resolver=None):
    """Parse an investing.com export into an ImportReport of Transactions.

    Pass a SymbolResolver built around a fetcher to have every symbol verified
    against the price provider. The default resolver has no provider, so symbols
    are translated but not checked.
    """
    if resolver is None:
        resolver = SymbolResolver()

    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    sections = split_sections(rows)
    report = ImportReport()

    if "Open Positions" not in sections:
        report.rejected.append((0, "no 'Open Positions' section found", []))
        return report

    blocks = [("Open Positions", False)]
    if include_closed and "Closed Positions" in sections:
        blocks.append(("Closed Positions", True))

    for name, closing in blocks:
        block = sections[name]
        header = block["header"]

        if header is None or _index_of(header, "Symbol") is None:
            report.rejected.append((0, f"section {name!r} has no usable header", []))
            continue

        for line_no, row in block["rows"]:
            # Each section ends with summary lines -- "Closed P/L","$130.00" and
            # friends -- which are far narrower than the header. Skip them
            # quietly; they are structure, not failed data.
            if len(row) < len(header) // 2:
                continue

            if len(row) != len(header):
                report.rejected.append((line_no, f"expected {len(header)} columns, got {len(row)}", row))
                continue
            report.transactions.extend(
                _read_lot(line_no, row, header, report, resolver, closing=closing)
            )

    # Chronological, so Portfolio.add_transaction never sees a SELL for a
    # position it has not opened yet.
    report.transactions.sort(key=lambda t: (t.transaction_date, 0 if t.transaction_type == "BUY" else 1))
    return report


def build_portfolio(path, name="imported", base_currency="USD", creation_date=None,
                    include_closed=True, resolver=None):
    """Read an export and return (Portfolio, ImportReport).

    The report is returned rather than logged: a rejected row means a position
    is missing, and the caller should decide whether that is acceptable. The same
    goes for a symbol that did not resolve, which arrives as a named warning.
    """
    report = read_transactions(path, include_closed=include_closed, resolver=resolver)

    if creation_date is None and report.transactions:
        creation_date = report.transactions[0].transaction_date

    portfolio = Portfolio(name, base_currency, creation_date=creation_date)

    for transaction in report.transactions:
        try:
            portfolio.add_transaction(transaction)
        except ValueError as exc:
            report.warnings.append(f"{transaction.ticker} {transaction.transaction_date}: {exc}")

    return portfolio, report
