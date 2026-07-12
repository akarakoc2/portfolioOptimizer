from pandas import Timestamp
from datetime import datetime
from scipy.optimize import brentq

class MWRCalculator():
    def __init__(self, cashflows, current_value, inception_date):
        self.cashflows = cashflows.copy()
        self.current_value = current_value
        self.inception_date = inception_date

        today = Timestamp(datetime.now())

        self.cashflows.append((today, current_value))
        self.cashflows = sorted(self.cashflows, key=lambda x: x[0])


    def _calculate_npv(self, r):
        npv = 0 

        for (date,amount) in self.cashflows:
            t = (date - self.inception_date).days / 365.25
            pv = amount / (1+r) ** (t)
            npv += pv

        return npv

    def calculate_mwr(self):
        try:
            mwr = brentq(
                lambda r: self._calculate_npv(r),
                -0.999,
                100
            )
            return mwr
        except ValueError:
            return None

        
        