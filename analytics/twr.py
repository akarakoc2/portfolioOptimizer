import pandas as pd

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
    
    #helper function to calculate the subperiod returns with the 0 handle
    def _calculate_subperiod_returns(self, start_date, end_date):

        start_value = self.portfolio_value.asof(start_date)
        end_value = self.portfolio_value.asof(end_date)

        if start_value == 0 or pd.isna(start_value):
            return 0
        
        return (end_value / start_value) - 1

    def calculate_twr(self):
        sub_returns = list()
        self.sub_periods = self._get_subperiod_boundries()

        
        for i in range(len(self.sub_periods) - 1):

            start_date = self.sub_periods[i]
            end_date = self.sub_periods[i+1]

            return_s = self._calculate_subperiod_returns(start_date, end_date)

            sub_returns.append(return_s)


        twr = 1.0
        for r in sub_returns:
            twr *= (1 + r)

        return twr - 1
            

            









        