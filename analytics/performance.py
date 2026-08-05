import pandas as pd

class PerformanceCalculator():
    """Risk and return metrics.

    Expects `portfolio_returns` to be the flow-adjusted daily series from
    PortfolioTimeSeries.portfolio_returns. Feeding it a raw pct_change of the
    value series is what produced a 252% "return" on a portfolio that made 36%:
    every deposit read as a one-day gain.
    """

    def __init__(self, portfolio_value, portfolio_returns, risk_free = 0):

        self.portfolio_value = portfolio_value
        self.portfolio_returns = portfolio_returns
        self.risk_free = risk_free

        self.trading_days = 252

    @property
    def growth_index(self):
        """Cumulative time-weighted growth of one unit of currency.

        Drawdown and total return come from here, never from portfolio_value --
        the value series steps up when you fund the account, this one only moves
        when the market does.
        """
        return (1 + self.portfolio_returns).cumprod()

    def _years_elapsed(self):
        span = self.portfolio_returns.index[-1] - self.portfolio_returns.index[0]
        return span.days / 365.25

    def total_return(self):
        if self.portfolio_returns.empty:
            return float('nan')

        growth_factors = self.portfolio_returns + 1
        total_return = growth_factors.prod() - 1

        return total_return

    def annualized_return(self):
        if self.portfolio_returns.empty:
            return float('nan')

        # Calendar time, not len(returns). Counting observations silently
        # assumes every year holds exactly 252 of them.
        years = self._years_elapsed()
        if years <= 0:
            return float('nan')

        growth = 1 + self.total_return()
        if growth <= 0:
            return -1.0

        ann_return = growth ** (1 / years) - 1

        return ann_return

    def volatility(self):
        if len(self.portfolio_returns) < 2:
            return float('nan')

        vol_daily = self.portfolio_returns.std()
        vol_ann = vol_daily * (self.trading_days ** 0.5)
        return vol_ann

    def sharpe_ratio(self):
        vol = self.volatility()
        if pd.isna(vol) or vol == 0:
            return float('nan')

        shp_ret = (self.annualized_return() - self.risk_free) / vol

        return shp_ret

    def max_drawdown(self):
        index = self.growth_index
        if index.empty:
            return float('nan')

        cum_max = index.cummax()
        max_dd = (index - cum_max) / cum_max
        return max_dd.min()

    def _calculate_window_return(self, start_date, end_date ):
        growth_factors = self.portfolio_returns.loc[start_date:end_date] + 1
        total_return = growth_factors.prod() - 1
        return total_return



    def get_tearsheet_returns(self):
        if self.portfolio_returns.empty:
            return {}

        anchor = self.portfolio_returns.index.max()
        inception_date = self.portfolio_returns.index.min()
        ytd_start = pd.Timestamp(year=anchor.year, month=1, day=1)


        target_months = {"1M":1, "3M":3, "6M":6, "1Y":12, "5Y": 60}

        target_days_returns = dict()
        for label, months in target_months.items():
            target_start = anchor - pd.DateOffset(months=months)

            # Clamping to inception used to label a 6-month-old portfolio's
            # return as its "5Y". Say we don't know instead.
            if target_start < inception_date:
                target_days_returns[label] = None
                continue

            target_days_returns[label] = self._calculate_window_return(
                start_date=target_start, end_date=anchor
            )

        if ytd_start < inception_date:
            ytd_start = inception_date
        target_days_returns["YTD"] = self._calculate_window_return(ytd_start, anchor)

        return target_days_returns
