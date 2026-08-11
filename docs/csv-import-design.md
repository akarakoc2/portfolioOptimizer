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

## Profile: investing.com holdings export

Filename looks like `My Holdings_Holdings_08082026.csv`. Verified against a
real export, August 2026.

### Structure

Not one table — three, stacked, with different column counts. A plain
`csv.DictReader` over the file will not work.

| rows | section | cols | use |
|------|---------|------|-----|
| 0–21 | `Open Positions Summary` | 53 | **skip** — aggregate of the next section, no dates |
| 23–46 | `Open Positions` | 20 | one row per lot, has `Open Date` |
| 48–79 | `Closed Positions` | 12 | one row per round trip, has `Open Date` and `Close Date` |

Split on single-cell rows, then parse each block against its own header.

### Reconstructing a ledger

This is a *holdings* export, not a transaction log, but the per-lot sections
carry enough to rebuild one:

- each **Open Positions** row → one `BUY` at `Open Date`
- each **Closed Positions** row → one `BUY` at `Open Date` **plus** one `SELL`
  at `Close Date`

Sanity check that the reconstruction is faithful: summed lot quantities must
equal the summary section's `Amount`. On the reference file ISCTR's two lots
(1215 + 2718) match its summary row of 3933.

Where the same symbol and open date appear on several closed rows with slightly
different amounts, treat each row as its own independent round trip. The net
position still lands at zero and the cash flows are right; trying to stitch
them into one partially-closed lot is guesswork.

### Known gaps in the source data

- **No commission on closed positions.** The column simply is not in that
  section, so sell-side fees are unavailable. Record zero and warn.
- **No dividends, deposits or withdrawals.** Nothing in the export represents
  them, so imported portfolios keep relying on auto-funding and on dividends
  derived from yfinance.
- **`Open Date` is the lot open, not necessarily a single purchase.** Fine for
  our purposes; noted so nobody reads it as trade-level truth.

### Symbol mapping

investing.com uses Reuters-style suffixes. Strip the exchange marker, keep the
country marker:

| suffix / exchange | rule | example |
|---|---|---|
| `.O` (NASDAQ) | strip | `MSFT.O` → `MSFT` |
| `.K` (NYSE Arca) | strip | `ROBO.K` → `ROBO` |
| `.IS` (Istanbul) | keep | `HALKB.IS` → `HALKB.IS` |
| no suffix, NYSE | keep | `V` → `V` |
| exchange `ETR` | **manual** | `BASFn` → `BAS.DE` |

All 13 currently-held symbols resolve under those rules, and the resulting
prices match the export's own `Current Price` column to the cent.

Four symbols in the closed section do not, and need an explicit override table:

| symbol | why | resolution |
|---|---|---|
| `BASFn` | Reuters suffix, not a Yahoo one | `BAS.DE` |
| `CBKG` | same | `CBK.DE` |
| `IAS.O` | taken private, delisted | no price history — exclude |
| `LP68048229` | Turkish fund code, not on Yahoo | no price history — exclude |

So the profile needs a hand-maintained `SYMBOL_OVERRIDES` dict alongside the
suffix rules, and unresolvable symbols must be a *warning that names them*, not
a silent drop.

### Cross-listings break the suffix rules outright

The rules above assume a symbol plus a venue suffix identifies a listing. On any
venue that cross-lists, it does not: a secondary listing has its own local
ticker, unrelated to the primary one.

| export row | suffix rule gives | actual Yahoo listing |
|---|---|---|
| `MSFT.DE` / `ETR` | `MSFT.DE` — delisted error | `MSF.DE` |
| `AAPL` / `ETR` | `AAPL.DE` — delisted error | `APC.DE` |
| `NVDA.DE` / `ETR` | `NVDA.DE` — delisted error | `NVD.DE` |

Nothing derives one from the other, so translation cannot be a function that
returns an answer. It has to return *candidates*, and something has to check
them. `SymbolResolver` does both:

1. `symbol_candidates()` orders the guesses — `SYMBOL_OVERRIDES`, then the
   seeded `LOCAL_LISTINGS` entry for the venue, then the plain suffix rule, then
   the bare symbol. Venue-consistent guesses come first because they are the
   only ones that keep the row's quote currency.
2. Each candidate is probed against the price provider; the first with price
   history wins. Without a provider the first candidate stands unverified,
   which is all an offline import can honestly claim.
3. Falling through to the bare symbol means pricing a Xetra row in dollars, so
   it warns *and* rewrites `Transaction.currency` to the venue that resolved.
   Leaving the row's `€` marker in place would have the FX layer convert a
   dollar price as though it were euros.
4. Decisions are cached in the fetcher's cache directory, negatives included —
   a symbol that resolves to nothing is the one probe the price cache cannot
   remember, since empty frames are never written.

`LOCAL_LISTINGS` is seeded with the common Xetra/US pairs so the frequent cases
never probe at all. Every entry was checked against the provider for company
name, currency and exchange, and that is the bar for adding one: a wrong entry
prices the wrong security in silence, which is worse than no entry.

### Field parsing

- **Dates** are `MM/DD/YYYY` (`07/19/2026` disambiguates it).
- **Money** carries a symbol, thousands separators, and sometimes a sign:
  `$1,234.56`, `₺12,345.00`, `-$67.89`. Strip to a number *and keep the symbol*
  — it is the only currency marker on the row.
- **Quantities** are fractional to 8 dp (`0.65100000`).
- `--` means not applicable; `-` means no value. Both are nulls.

### Currency

The blocker for this file. Market values are quoted in the instrument's own
currency — `$1,234.56` for a US listing, `₺12,345.00` for an Istanbul one — so a
part-Turkish book has a substantial share of its value in a column that cannot
be added to the rest. Summing those columns without conversion is meaningless.

Worth knowing: the export's own reported total will not match converting the
parts at today's USDTRY, and the gap is several percent. It is entirely a
question of which rate was used and when, which is exactly the design question:

- **cost basis** converts at the transaction date
- **market value** converts at each daily valuation date

Do both and FX movement lands in the return, which is correct for a
USD-reporting holder. `USDTRY=X` is available through the existing fetcher, so
the data is not the hard part — threading a per-currency rate series through
`build_price_frames` and `build_cash_and_flows` is.

**Currency conversion has to land before this profile is useful.** A
US-only subset of the file would import correctly today; the whole thing
would not.

## Deliberately out of scope

- **Currency conversion.** Import can *record* a currency and warn on a
  mismatch, but converting needs an FX rate series and a decision about whether
  FX is reported as a separate return contributor. Separate piece of work.
- **Tax lots.** Average cost is the current model. FIFO/LIFO changes
  `Position`, not the importer.
- **Transfers in.** A position moved from another broker has a cost basis but
  no purchase cash flow. Representable as `DEPOSIT` + `BUY` on the same date,
  which is worth documenting rather than special-casing.
