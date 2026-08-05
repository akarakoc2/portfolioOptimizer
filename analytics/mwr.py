from pandas import Timestamp
from datetime import datetime
from scipy.optimize import brentq

class MWRCalculator():
    """Money-weighted return (IRR) on external cash flows.

    `cashflows` must be *external* flows only -- money crossing the portfolio
    boundary, signed from the holder's point of view (negative when you put
    money in). Feeding it every trade would count selling one holding to buy
    another as a withdrawal followed by a contribution, which it isn't. See
    PortfolioTimeSeries.external_cashflows.

    Unlike TWR, this is sensitive to *when* you added money, which is exactly
    what it is for: TWR grades the strategy, MWR grades your timing.
    """

    def __init__(self, cashflows, current_value, inception_date, terminal_date = None):
        self.cashflows = list(cashflows)
        self.current_value = current_value
        self.inception_date = Timestamp(inception_date)

        # The terminal value has to be dated to the valuation it came from.
        # datetime.now() drifts away from portfolio_value.index[-1] on weekends
        # and stale caches, quietly shortening the last period.
        if terminal_date is None:
            terminal_date = Timestamp(datetime.now())
        self.terminal_date = Timestamp(terminal_date)

        self.cashflows.append((self.terminal_date, current_value))
        self.cashflows = sorted(self.cashflows, key=lambda x: x[0])


    def _calculate_npv(self, r):
        npv = 0

        for (date,amount) in self.cashflows:
            t = (date - self.inception_date).days / 365.25
            pv = amount / (1+r) ** (t)
            npv += pv

        return npv

    def calculate_mwr(self):
        amounts = [amount for _, amount in self.cashflows]

        # An IRR needs at least one flow of each sign to bracket a root.
        # Without this brentq just raises and the failure looks like a bug.
        if not amounts or min(amounts) >= 0 or max(amounts) <= 0:
            return float('nan')

        try:
            mwr = brentq(
                lambda r: self._calculate_npv(r),
                -0.999,
                100
            )
            return mwr
        except ValueError:
            # No sign change in the bracket: the IRR lies outside [-99.9%, 10000%].
            return float('nan')
