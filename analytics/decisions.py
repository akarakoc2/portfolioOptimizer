"""Was the decision any good?

Two questions the return metrics cannot answer. Did picking stocks beat simply
indexing the money as it arrived, and what did the sales cost.
"""

import pandas as pd


def cashflow_matched_benchmark(timeseries, benchmark_ticker="SPY", fetcher=None):
    """Buy the benchmark with each contribution, on the day it arrived.

    The honest comparison. Total return against an index flatters or punishes a
    portfolio depending only on when capital showed up -- an index that never
    received your deposits is not a like-for-like alternative. This one gets the
    same money on the same dates.

    Uses external cash flows, so a sale that funded a purchase is correctly
    absent: it was never new money and the benchmark is not credited with it.
    """
    fetcher = fetcher or timeseries.fetcher
    value = timeseries.portfolio_value()
    flows = timeseries.external_cashflows

    if not flows:
        raise ValueError("No external cash flows; nothing to match a benchmark against.")

    prices = fetcher.get_historical_prices(benchmark_ticker, value.index[0], value.index[-1])
    if prices is None or prices.empty:
        raise ValueError(f"No price history for benchmark {benchmark_ticker!r}.")

    prices = prices["Close"].squeeze()
    prices.index = pd.DatetimeIndex(prices.index)
    if prices.index.tz is not None:
        prices.index = prices.index.tz_localize(None)
    prices = prices.reindex(value.index).ffill().bfill()

    units = 0.0
    unit_history = {}
    for date, amount in flows:
        contribution = -amount                       # negative when money goes in
        if contribution <= 0:
            continue                                 # withdrawals are not purchases
        units += contribution / float(prices.loc[date])
        unit_history[date] = units

    contributed = sum(-a for _, a in flows if a < 0)
    benchmark_units = pd.Series(unit_history).reindex(value.index).ffill().fillna(0.0)

    return {
        "contributed": contributed,
        "portfolio_value": float(value.iloc[-1]),
        "benchmark_value": float(units * prices.iloc[-1]),
        "portfolio_gain": float(value.iloc[-1]) / contributed - 1,
        "benchmark_gain": float(units * prices.iloc[-1]) / contributed - 1,
        "active_value_added": float(value.iloc[-1]) - float(units * prices.iloc[-1]),
        # Both series on one axis: what the account did, versus what the same
        # deposits would have done in the index.
        "portfolio_series": value,
        "benchmark_series": benchmark_units * prices,
    }


def sale_opportunity_cost(portfolio, fetcher, timeseries, as_of=None):
    """For each closed position, proceeds versus what it would be worth now.

    A positive number is what selling gave up. Read it as the cost of that sale
    *in isolation* -- it assumes the proceeds sat idle, and they did not. Use
    cashflow_matched_benchmark for the bottom line; this is for spotting which
    specific holdings were worth keeping.

    Everything is converted to base currency at the rate prevailing on each
    date, so a lira sale is not compared against a dollar valuation.
    """
    as_of = pd.Timestamp(as_of) if as_of is not None else timeseries.trading_days[-1]
    currencies = timeseries.instrument_currencies
    prices = timeseries.build_price_frames() * timeseries.build_fx_frames()
    fx = timeseries.build_fx_frames()

    rows = []
    for position in portfolio.all_positions():
        sales = [t for t in position.transactions if t.transaction_type == "SELL"]
        if not sales or position.is_open:
            continue

        ticker = position.ticker
        quantity_sold = sum(t.quantity * timeseries.split_factor(ticker, t.transaction_date)
                            for t in sales)

        proceeds = 0.0
        for sale in sales:
            day = timeseries._snap_to_trading_day(sale.transaction_date)
            proceeds += sale.total_cost * float(fx.loc[day, ticker])

        last_price = float(prices.loc[:as_of, ticker].iloc[-1])
        worth_now = quantity_sold * last_price
        exit_date = max(t.transaction_date for t in sales)

        rows.append({
            "ticker": ticker,
            "currency": currencies[ticker],
            "exit_date": exit_date,
            "quantity": quantity_sold,
            "proceeds": proceeds,
            "worth_now": worth_now,
            "sale_cost": worth_now - proceeds,
            "sale_cost_pct": (worth_now - proceeds) / proceeds if proceeds else float("nan"),
        })

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    return frame.sort_values("sale_cost", ascending=False).reset_index(drop=True)


def realisation_asymmetry(portfolio, timeseries):
    """Are gains realised while losses are held?

    Compares closed positions against open ones. A high share of closes at a
    gain sitting alongside open positions at a loss is the disposition effect,
    and it is worth seeing before the next sale rather than a year afterwards.
    """
    prices = timeseries.build_price_frames() * timeseries.build_fx_frames()
    last = prices.iloc[-1]

    closed_returns = []
    open_returns = []

    for position in portfolio.all_positions():
        buys = [t for t in position.transactions if t.transaction_type == "BUY"]
        if not buys:
            continue
        cost_per_share = sum(t.quantity * t.cost_per_unit for t in buys) / sum(t.quantity for t in buys)

        if position.is_open:
            factor = timeseries.split_factor(position.ticker, buys[0].transaction_date)
            native_now = float(last[position.ticker]) / float(
                timeseries.build_fx_frames().iloc[-1][position.ticker]
            )
            open_returns.append(native_now / (cost_per_share / factor) - 1)
        else:
            sales = [t for t in position.transactions if t.transaction_type == "SELL"]
            if not sales:
                continue
            exit_per_share = sum(t.quantity * t.cost_per_unit for t in sales) / sum(t.quantity for t in sales)
            closed_returns.append(exit_per_share / cost_per_share - 1)

    def _mean(values):
        return sum(values) / len(values) if values else float("nan")

    gains = [r for r in closed_returns if r > 0]
    losses = [r for r in open_returns if r < 0]

    return {
        "closed_positions": len(closed_returns),
        "closed_at_gain": len(gains),
        "closed_win_rate": len(gains) / len(closed_returns) if closed_returns else float("nan"),
        "avg_realised_return": _mean(closed_returns),
        "avg_realised_gain": _mean(gains),
        "open_positions": len(open_returns),
        "open_at_loss": len(losses),
        "avg_open_return": _mean(open_returns),
        "avg_open_loss": _mean(losses),
    }
