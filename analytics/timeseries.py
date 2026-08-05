from domain.portfolio import Portfolio
from domain.position import Position
from domain.transaction import Transaction
from datetime import datetime
import pandas as pd

class PortfolioTimeSeries():
    """Daily valuation of a portfolio, with cash tracked explicitly.

    Funding model: the account is funded on demand. A BUY that costs more than
    the current cash balance implicitly deposits the shortfall, and *that
    deposit* is the external cash flow. Sale proceeds stay in cash until they
    are redeployed.

    That distinction is the whole point. Selling MSFT to buy AAPL spends cash
    the portfolio already had, so it produces no external flow and cannot show
    up as performance. Only money crossing the portfolio boundary gets stripped
    out of returns.
    """

    def __init__(self, portfolio, fetcher, start_date = None, end_date = None):
        self.portfolio = portfolio
        if start_date is None:
            self.start_date = self._first_transaction_date
        else:
            self.start_date = start_date
        if end_date is None:
            self.end_date = datetime.now()
        else:
            self.end_date = end_date

        self.fetcher = fetcher
        self.tickers = self.portfolio.positions.keys()
        self.trading_days = pd.bdate_range(self.start_date, self.end_date)

        if len(self.trading_days) == 0:
            raise ValueError(
                f"No trading days between {self.start_date} and {self.end_date}."
            )

        # build_price_frames hits the fetcher and everything downstream asks for
        # these repeatedly, so build each at most once.
        self._holding_frames = None
        self._price_frames = None
        self._cash_and_flows = None

    def _snap_to_trading_day(self, when):
        """First trading day on or after `when`.

        A transaction dated on a weekend or market holiday has no row in the
        business-day index. Snapping it forward is what stops the reindex in
        build_holding_frames from dropping the position entirely.
        """
        when = pd.Timestamp(when).normalize()
        position = self.trading_days.searchsorted(when, side="left")
        if position >= len(self.trading_days):
            return self.trading_days[-1]
        return self.trading_days[position]

    def _ordered_transactions(self):
        """(trading_day, transaction) pairs in the order they settle.

        Same-day SELLs come before BUYs so proceeds are available to fund a
        same-day purchase. Without that, a straight rotation would look like a
        deposit followed by an idle cash balance.
        """
        rows = []
        for position in self.portfolio.positions.values():
            for transaction in position.transactions:
                day = self._snap_to_trading_day(transaction.transaction_date)
                rows.append((day, transaction))

        rows.sort(key=lambda row: (row[0], 0 if row[1].transaction_type == "SELL" else 1))
        return rows

    def build_holding_frames(self):
        if self._holding_frames is not None:
            return self._holding_frames

        list_dicts = []

        for date, transaction in self._ordered_transactions():
            ticker = transaction.ticker

            if transaction.transaction_type == 'BUY':
                quantity_norm = transaction.quantity
            else:
                quantity_norm = - transaction.quantity

            list_dicts.append({"date": date, "ticker": ticker, "quantity": quantity_norm})

        if not list_dicts:
            self._holding_frames = pd.DataFrame(0.0, index=self.trading_days, columns=list(self.tickers))
            return self._holding_frames

        df = pd.DataFrame(list_dicts)
        df = df.pivot_table(index="date", columns="ticker", values="quantity", aggfunc="sum")
        df = df.cumsum()
        # Lossless now: every date above is already a trading day.
        df = df.reindex(self.trading_days)
        df = df.ffill()
        df = df.fillna(0.0)

        self._holding_frames = df
        return df

    def build_price_frames(self):
        if self._price_frames is not None:
            return self._price_frames

        prices = dict()
        ticker_starts = self.ticker_start_dates

        for ticker in self.tickers:
            ticker_start = ticker_starts[ticker]
            data = self.fetcher.get_historical_prices(
                ticker=ticker,
                start_date=ticker_start,
                end_date=self.end_date
            )
            # Skipping a failed ticker used to leave it out of the frame, where
            # sum(skipna=True) quietly valued the position at zero. Refuse instead.
            if data is None or data.empty:
                raise ValueError(
                    f"No price data returned for {ticker!r} between {ticker_start.date()} "
                    f"and {pd.Timestamp(self.end_date).date()}. Refusing to continue -- the "
                    f"position would silently drop out of the portfolio value."
                )
            prices[ticker] = data["Close"].squeeze()

        prices_df = pd.DataFrame(prices)
        if prices_df.index.tz is not None:
            prices_df.index = prices_df.index.tz_localize(None)
        prices_df = prices_df.reindex(self.trading_days)
        prices_df = prices_df.ffill()
        # No fillna(0): a missing price is not a price of zero. Leading NaNs are
        # harmless because holdings are zero there, and build_value_frame checks.

        self._price_frames = prices_df
        return prices_df


    def build_value_frame(self):
        holding_frames = self.build_holding_frames()
        build_prices = self.build_price_frames()
        daily_values = holding_frames * build_prices

        missing = daily_values.isna() & (holding_frames != 0)
        if missing.any().any():
            gaps = missing.any()
            raise ValueError(
                f"Holding a position with no price on some days: {list(gaps[gaps].index)}."
            )

        return daily_values.fillna(0.0)

    def build_cash_and_flows(self):
        """Daily cash balance and daily *external* cash flow.

        Returns (cash, flows), both on trading days. `flows` is positive when
        money enters from outside, and zero on days where trading only moved
        value between cash and holdings.
        """
        if self._cash_and_flows is not None:
            return self._cash_and_flows

        cash = 0.0
        cash_by_date = {}
        flow_by_date = {}

        for date, transaction in self._ordered_transactions():
            if transaction.transaction_type == "BUY":
                cost = transaction.total_cost              # price * qty + fees
                if cost > cash:
                    deposit = cost - cash
                    flow_by_date[date] = flow_by_date.get(date, 0.0) + deposit
                    cash += deposit
                cash -= cost
            else:
                cash += transaction.total_cost             # price * qty - fees
            cash_by_date[date] = cash

        if cash_by_date:
            cash_series = pd.Series(cash_by_date).sort_index()
            cash_series = cash_series.reindex(self.trading_days).ffill().fillna(0.0)
        else:
            cash_series = pd.Series(0.0, index=self.trading_days)

        if flow_by_date:
            flow_series = pd.Series(flow_by_date).sort_index()
            flow_series = flow_series.reindex(self.trading_days).fillna(0.0)
        else:
            flow_series = pd.Series(0.0, index=self.trading_days)

        self._cash_and_flows = (cash_series, flow_series)
        return self._cash_and_flows

    def portfolio_value(self):
        """Total portfolio value: holdings marked to market, plus cash.

        Counting cash is what keeps the series continuous through a full
        liquidation -- a portfolio sold to cash is worth what it sold for, not
        nothing.
        """
        holdings_value = self.build_value_frame().sum(axis=1)
        cash, _ = self.build_cash_and_flows()
        portfolio_val = holdings_value + cash

        # Trim only the leading unfunded stretch. The old `> 0` filter deleted
        # interior days too, letting pct_change link straight across the gap.
        funded = portfolio_val.to_numpy().nonzero()[0]
        if len(funded) == 0:
            return portfolio_val.iloc[0:0]

        return portfolio_val.iloc[funded[0]:]

    def portfolio_returns(self):
        """Daily time-weighted returns, with external cash flows removed.

            r_t = V_t / (V_t-1 + F_t) - 1

        Flows are treated as arriving at the start of the day, which is what
        makes the inception day well defined: V_t-1 is zero there, so the
        denominator is the cash actually deposited and the first return is the
        move from your fill price to that day's close, less fees.
        """
        port_val = self.portfolio_value()
        _, flows = self.build_cash_and_flows()
        flows = flows.reindex(port_val.index).fillna(0.0)

        invested_base = port_val.shift(1).fillna(0.0) + flows
        percentage_chg = port_val / invested_base - 1

        percentage_chg = percentage_chg.replace([float('inf'), float('-inf')], float('nan'))
        percentage_chg = percentage_chg[invested_base > 0]
        percentage_chg = percentage_chg.dropna()
        return percentage_chg


    @property
    def cashflow_dates(self):
        dates = []
        for position in self.portfolio.positions.values():
            for transaction in position.transactions:
                date = transaction.transaction_date
                dates.append(pd.Timestamp(date))


        return sorted(list(set(dates)))

    @property
    def external_cashflows(self):
        """External flows as (date, amount) from the holder's point of view.

        Negative when you put money in. Internal reallocation is deliberately
        absent -- this is what MWR/IRR consumes, and rotating between holdings
        is not a contribution.
        """
        _, flows = self.build_cash_and_flows()
        return [(date, -amount) for date, amount in flows.items() if amount != 0]

    @property
    def ticker_start_dates(self):
        start_dates = {}

        # min(), not transactions[0] -- nothing sorts that list, so the first
        # element is only the earliest if they happened to be entered in order.
        for ticker, position in self.portfolio.positions.items():
            start_dates[ticker] = min(
                pd.Timestamp(t.transaction_date) for t in position.transactions
            )

        return start_dates

    @property
    def _first_transaction_date(self):
        start_dates = self.ticker_start_dates
        if not start_dates:
            raise ValueError("Portfolio has no transactions; cannot build a time series.")
        return min(start_dates.values())
