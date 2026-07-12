
class TWRcalculator():
    def __init__(self,portfolio_value, cashflow_dates ):
        
        self.portfolio_value = portfolio_value
        self.cashflow_dates = cashflow_dates
        self.inception_date = portfolio_value.index.min()
        self.end_date = portfolio_value.index.max()


    def _get_subperiod_boundries(self):

        boundaries = self.cashflow_dates.copy()
        boundaries.insert(0, self.inception_date)
        boundaries.append(self.end_date)
        boundaries = list(set(boundaries))
        boundaries = sorted(boundaries)

        return boundaries






        