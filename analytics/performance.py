import pandas as pd

class PerformanceCalculator():
    def __init__(self, portfolio_value, portfolio_returns, risk_free = 0):
        
        self.portfolio_value = portfolio_value
        self.portfolio_returns = portfolio_returns
        self.risk_free = risk_free
        
        self.trading_days = 252

    def total_return(self):

        growth_factors = self.portfolio_returns + 1
        total_return = growth_factors.prod() - 1 

        return total_return
    
    def annualized_return(self):
        total_days = len(self.portfolio_returns)
        growth_factors = self.portfolio_returns + 1
        total_ret = growth_factors.prod() - 1 
        ann_return = (1 + total_ret)**(self.trading_days/total_days) - 1

        return ann_return

    def volatility(self):

        vol_daily = self.portfolio_returns.std()
        vol_ann = vol_daily * (self.trading_days ** 0.5)
        return vol_ann

    def sharpe_ratio(self):

        shp_ret = (self.annualized_return() - self.risk_free) / self.volatility()

        return shp_ret
    
    def max_drawdown(self):
        cum_max = self.portfolio_value.cummax()
        max_dd = (self.portfolio_value - cum_max) / cum_max
        return max_dd.min()

    def _calculate_window_return(self, start_date, end_date ):
        growth_factors = self.portfolio_returns.loc[start_date:end_date] + 1
        total_return = growth_factors.prod() - 1 
        return total_return
        


        
    def get_tearsheet_returns(self):
        anchor = self.portfolio_returns.index.max()
        inception_date = self.portfolio_returns.index.min()
        ytd_start = pd.Timestamp(year=anchor.year, month=1, day=1)
        

        target_days = {"1M":1, "3M":3, "6M":6, "1Y":12, "5Y": 60}

        target_days_returns = dict()
        for label, days in target_days.items(): 
            target_start = anchor - pd.DateOffset(months=days)
            
            
            if target_start < inception_date:
                    target_start = inception_date

            port_ret = self._calculate_window_return(start_date=target_start, end_date = anchor)
            target_days_returns["YTD"] = self._calculate_window_return(ytd_start, anchor)
            target_days_returns[label] = port_ret

        return target_days_returns

    
            


        









