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
"""

import csv
import re
from dataclasses import dataclass, field

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
_EXCHANGE_SUFFIX = {"ETR": ".DE", "IS": ".IS"}

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


def to_yahoo_symbol(symbol, exchange=""):
    """Translate an investing.com symbol to its Yahoo equivalent."""
    symbol = symbol.strip()

    if symbol in SYMBOL_OVERRIDES:
        return SYMBOL_OVERRIDES[symbol]

    # Longest suffix first, so '.IS' is not matched as a bare '.I'.
    for suffix in sorted(_SUFFIX_RULES, key=len, reverse=True):
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)] + _SUFFIX_RULES[suffix]

    return symbol + _EXCHANGE_SUFFIX.get(exchange.strip().upper(), "")


def currency_for_symbol(yahoo_symbol):
    """Quote currency implied by a Yahoo listing suffix. US listings have none."""
    for suffix in sorted(_SUFFIX_CURRENCY, key=len, reverse=True):
        if yahoo_symbol.endswith(suffix):
            return _SUFFIX_CURRENCY[suffix]
    return "USD"


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


def _read_lot(line_no, row, header, report, *, closing=False):
    """Turn one lot row into one or two Transactions. Returns a list."""
    symbol = row[_index_of(header, "Symbol")].strip()
    exchange = row[_index_of(header, "Exchange")].strip()

    if not symbol:
        report.rejected.append((line_no, "no symbol", row))
        return []

    if symbol in UNSUPPORTED:
        report.warnings.append(
            f"line {line_no}: {symbol} has no Yahoo listing; position excluded"
        )
        return []

    ticker = to_yahoo_symbol(symbol, exchange)

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


def read_transactions(path, include_closed=True):
    """Parse an investing.com export into an ImportReport of Transactions."""
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
            report.transactions.extend(_read_lot(line_no, row, header, report, closing=closing))

    # Chronological, so Portfolio.add_transaction never sees a SELL for a
    # position it has not opened yet.
    report.transactions.sort(key=lambda t: (t.transaction_date, 0 if t.transaction_type == "BUY" else 1))
    return report


def build_portfolio(path, name="imported", base_currency="USD", creation_date=None,
                    include_closed=True):
    """Read an export and return (Portfolio, ImportReport).

    The report is returned rather than logged: a rejected row means a position
    is missing, and the caller should decide whether that is acceptable.
    """
    report = read_transactions(path, include_closed=include_closed)

    if creation_date is None and report.transactions:
        creation_date = report.transactions[0].transaction_date

    portfolio = Portfolio(name, base_currency, creation_date=creation_date)

    for transaction in report.transactions:
        try:
            portfolio.add_transaction(transaction)
        except ValueError as exc:
            report.warnings.append(f"{transaction.ticker} {transaction.transaction_date}: {exc}")

    return portfolio, report
