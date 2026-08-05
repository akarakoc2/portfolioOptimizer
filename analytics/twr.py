import pandas as pd

class TWRcalculator():
    """Time-weighted return.

    Once the daily return series already has external flows stripped out (see
    PortfolioTimeSeries.portfolio_returns), TWR is nothing more than the
    geometric linking of those returns. There are no subperiod boundaries to
    find and no valuations to look up.

    The previous implementation walked subperiods between cash-flow dates,
    which is what you do when you can only value the portfolio *at* those
    dates. With a daily price series that detour is both less accurate and
    considerably more code, so it's gone.

    Note this returns the same number as PerformanceCalculator.total_return, by
    construction -- that agreement is the point, not a redundancy. They used to
    disagree because only one of them adjusted for flows.
    """

    def __init__(self, portfolio_returns):
        self.portfolio_returns = portfolio_returns

    def calculate_twr(self):
        if self.portfolio_returns.empty:
            return float('nan')

        return (1 + self.portfolio_returns).prod() - 1

    def annualized_twr(self):
        if self.portfolio_returns.empty:
            return float('nan')

        span = self.portfolio_returns.index[-1] - self.portfolio_returns.index[0]
        years = span.days / 365.25
        if years <= 0:
            return float('nan')

        growth = 1 + self.calculate_twr()
        if growth <= 0:
            return -1.0

        return growth ** (1 / years) - 1
