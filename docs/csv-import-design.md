# CSV import — architecture

How transaction data gets from a broker export into a `Portfolio`.

## The problem this has to solve

Today a portfolio is built by writing Python:

```python
portfolio.add_transaction(Transaction('aapl', '2024-01-02', 'BUY', 5, 185, 2, 'USD'))
```

Three things break when the data comes from a file instead.

**The domain cannot represent funding or income.** `Transaction.VALID_TYPES` is
`{BUY, SELL}` and every transaction is routed into a `Position`, which requires
a ticker. A deposit has no ticker. A real export has deposits, withdrawals,
dividends, and often interest and account fees. Those rows have nowhere to go.

**Rows arrive unsorted and dirty.** Broker CSVs disagree on column names, date
formats, sign conventions, and whether fees are a column or a separate row. A
sale may appear before the purchase that covers it.

**Failures must be visible.** A row that silently fails to parse is a position
missing from the portfolio, and every number downstream is quietly wrong. The
value series has no way to tell you a row went missing.

## Shape

```
   broker.csv
       │
       ▼
┌──────────────┐   raw rows, no interpretation
│   Reader     │   dialect sniffing, encoding, header detection
└──────────────┘
       │  list[dict]
       ▼
┌──────────────┐   column names → canonical fields
│   Mapping    │   per-broker profile (YAML or dict)
└──────────────┘
       │  list[dict] with known keys
       ▼
┌──────────────┐   types, ranges, enums; collects errors, does not raise
│  Validation  │   → ImportReport(events, rejected, warnings)
└──────────────┘
       │  list[LedgerEvent]
       ▼
┌──────────────┐   ordering, oversell checks, unknown tickers
│ Reconcile    │
└──────────────┘
       │
       ▼
   Portfolio  ──►  PortfolioTimeSeries ──►  everything else, unchanged
```

Each stage has one job and is testable without the next. The layer boundary
that matters most is **Validation returns a report rather than raising** — one
bad row in a 500-row export should not cost you the other 499.

## The domain change this depends on

This is the piece to settle before writing the reader.

`Transaction` currently means "a trade". It needs to become one case of a
broader idea — call it a **ledger event** — covering everything that moves
cash or shares:

| type | ticker | changes shares | changes cash | external flow? |
|------|--------|----------------|--------------|----------------|
| `BUY` | yes | + | − | only the shortfall |
| `SELL` | yes | − | + | no |
| `DEPOSIT` | no | — | + | yes |
| `WITHDRAW` | no | — | − | yes |
| `DIVIDEND` | yes | — | + | no (income) |
| `FEE` / `INTEREST` | no | — | ± | no |

The last column is the one that matters for correctness, and it is already the
distinction `build_cash_and_flows` is built around. Everything else follows.

Two options for the model:

**A — widen `Transaction`.** Add the types, make `ticker` optional, and have
`Portfolio.add_transaction` route trades to `Position` and everything else to a
new `Portfolio.cash_events` list. Smaller diff, but `Transaction` ends up with
fields that are meaningless for half its cases (`quantity` on a deposit).

**B — introduce `LedgerEvent` as the base, keep `Transaction` as the trade
case.** `Portfolio` holds an event log; `Position` is derived from the trade
subset rather than being the primary store. Cleaner, and it makes the event log
the single source of truth — which is what a CSV import naturally produces.

**Recommendation: B**, because the event log is what you are importing. A is
faster now and will be refactored into B the first time you add interest or a
transfer-in.

Either way `Position` keeps its current role; it just stops being where cash
events have to squeeze through.

## What changes in the pipeline

Modest, because the cash account already exists.

`build_cash_and_flows` currently *infers* funding: a BUY that exceeds the cash
balance implicitly deposits the shortfall. With explicit `DEPOSIT` rows it
should prefer what was recorded and fall back to inference only when the
recorded deposits do not cover a purchase. That keeps existing hand-built
portfolios working while making imported ones exact.

```python
# sketch
for event in events_on(day):
    if event.type == "DEPOSIT":
        cash += event.amount
        external_flow[day] += event.amount
    elif event.type == "BUY":
        if event.total_cost > cash:
            shortfall = event.total_cost - cash      # auto-funding fallback
            external_flow[day] += shortfall
            cash += shortfall
        cash -= event.total_cost
    ...
```

Dividends already flow through `build_dividend_income`, which derives them from
yfinance. Imported `DIVIDEND` rows should **override** the derived ones for
dates they cover — the broker knows what you were actually paid, net of
withholding, and yfinance does not. Do not add both; that double-counts.

## Broker profiles

Do not write one parser per broker. Write one parser and a mapping per broker:

```python
DEGIRO = {
    "date":     ("Datum", "%d-%m-%Y"),
    "ticker":   "Product",
    "type":     {"Koop": "BUY", "Verkoop": "SELL", "iDEAL Deposit": "DEPOSIT"},
    "quantity": "Aantal",
    "price":    "Koers",
    "fees":     "Transactiekosten",
    "currency": "Mutatie",
}
```

A profile is data, not code, so adding a broker is a dict rather than a module,
and a profile can be tested against a three-row fixture.

Include a `GENERIC` profile matching the canonical column names, so anyone can
export from a spreadsheet without writing a profile at all.

## Validation rules

Reject the row, record why, continue:

- date unparseable, or in the future
- `type` not in the known set after mapping
- `quantity <= 0`, `price < 0`, `fees < 0`
- currency not in `VALID_CURRENCIES`
- ticker empty, or missing on a row type that requires one

Warn but accept:

- duplicate rows (same date, ticker, type, quantity, price) — usually a
  double-import, occasionally real
- a ticker yfinance does not resolve — only detectable later, so surface it
  from the price fetch rather than the parser
- currency differing from the portfolio's base, until FX conversion exists

Fail the whole import only for structural problems: no recognisable header, an
empty file, a profile whose required columns are absent.

## Report

```python
@dataclass
class ImportReport:
    events: list[LedgerEvent]
    rejected: list[tuple[int, dict, str]]   # line number, raw row, reason
    warnings: list[str]

    @property
    def ok(self) -> bool: ...
    def summary(self) -> str: ...
```

Line numbers matter — "row 47: date '31/02/2024' is not a valid date" is
actionable, "3 rows failed" is not.

## Testing

Fixture CSVs under `tests/fixtures/`, a handful of rows each: a clean generic
export, one per broker profile, and a deliberately broken one covering each
rejection rule. Assert on the `ImportReport`, not on exceptions.

The property worth pinning: **importing a CSV and building the same portfolio
by hand produce identical `portfolio_value` series.** That one test protects
the whole path.

## Order to build

1. `LedgerEvent` and the widened type set, with `Portfolio` holding an event log
2. `build_cash_and_flows` prefers recorded deposits, falls back to inference
3. Generic reader + validation + `ImportReport`
4. One real broker profile, driven by an actual export
5. Imported `DIVIDEND` rows override the yfinance-derived ones

Steps 1 and 2 are the ones that touch existing behaviour, so they want the
tests. Steps 3 to 5 are additive.

## Deliberately out of scope

- **Currency conversion.** Import can *record* a currency and warn on a
  mismatch, but converting needs an FX rate series and a decision about whether
  FX is reported as a separate return contributor. Separate piece of work.
- **Tax lots.** Average cost is the current model. FIFO/LIFO changes
  `Position`, not the importer.
- **Transfers in.** A position moved from another broker has a cost basis but
  no purchase cash flow. Representable as `DEPOSIT` + `BUY` on the same date,
  which is worth documenting rather than special-casing.
